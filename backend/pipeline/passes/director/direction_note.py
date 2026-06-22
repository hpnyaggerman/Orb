"""
passes/director/direction_note.py -- Direction-note step.

Asks the model, via a forced ``record_direction_note`` call, whether anything from
this turn should persist for the rest of the branch. Runs as a standalone sub-call
gated by the master Writing switch and the enabled ``field_type='direction_note'``
fragments whose timing matches this placement; each filled parameter becomes one
labelled note (empty when nothing is worth recording).

The wire schema in the shared per-turn tool blob is the union of every direction-note
fragment, held byte-stable so both placements reuse the cached base and only force the
tool choice. Each call is handed just its timing group, which shapes the request text
and the extraction. The trailing depends on placement: the post-turn placement replays
the writer's user message and reply to extend the warm writer/editor prefix; the
pre-writer placement appends only the request, carrying this turn's scene direction
inside it.

Errors and aborts are swallowed into an empty result. The post-turn placement runs
immediately before the turn's ``_result`` is emitted, so a propagating exception
would skip persistence of the finished reply -- recording a note must never do that.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping, Sequence

from ....core import ChatMessage, ContentPart, extract_hyperparams
from ....inference import (
    RECORD_DIRECTION_NOTE_CHOICE,
    CachedBase,
    LLMClient,
    build_direction_note_prompt,
    build_direction_note_tool,
    parse_tool_calls,
    reasoning_cfg,
)

logger = logging.getLogger(__name__)


@dataclass
class DirectionNoteResult:
    """Typed result of the direction-note step, yielded as the ``done`` payload.

    ``notes`` holds one ``{interactive_fragment_id, interactive_fragment_label, content}`` row per filled
    category parameter; empty when nothing is worth recording.
    """

    notes: list[dict] = field(default_factory=list)
    agent_raw: str = ""


def extract_direction_notes(
    tool_calls: list[dict],
    direction_note_fragments: Sequence[Mapping[str, Any]],
) -> list[dict]:
    """Turn parsed ``record_direction_note`` calls into labelled note rows.

    Each filled parameter is keyed by a direction-note fragment's id and becomes one note
    carrying that fragment's label, denormalised so a later rename or deletion of the
    fragment cannot orphan the note's heading. Parameters for unknown ids and blank or
    non-string values are dropped (a malformed model reply records nothing); a later
    call wins on key collisions.
    """
    labels = {df["id"]: (df.get("injection_label") or df.get("label") or df["id"]) for df in direction_note_fragments}
    values: dict[str, str] = {}
    for tc in tool_calls:
        if tc.get("name") == "record_direction_note":
            for k, v in (tc.get("arguments", {}) or {}).items():
                if k in labels and isinstance(v, str) and v.strip():
                    values[k] = v.strip()
    return [
        {"interactive_fragment_id": fid, "interactive_fragment_label": labels[fid], "content": c} for fid, c in values.items()
    ]


async def direction_note_step(
    client: LLMClient,
    base: CachedBase,
    *,
    settings: Mapping[str, Any],
    direction_note_fragments: Sequence[Mapping[str, Any]],
    active_notes: Sequence[Mapping[str, Any]],
    placement: str,
    inj_block: str | None = None,
    reply_text: str | None = None,
    writer_user_msg: "str | list[ContentPart] | None" = None,
    kv_tracker=None,
    reasoning_on: bool = False,
) -> AsyncIterator[dict]:
    """Yield reasoning chunks during the call, then a single done dict.

    Yields:
        ``{"type": "reasoning", "delta": str}``
        ``{"type": "done", "result": DirectionNoteResult}``
    """
    if not direction_note_fragments:
        yield {"type": "done", "result": DirectionNoteResult()}
        return

    # This placement's timing group only -- echoed into the request so the model is asked
    # to fill just these categories. The wire schema in the shared base is the wider union.
    tool_schema = build_direction_note_tool(direction_note_fragments)

    request = build_direction_note_prompt(
        active_notes,
        direction_note_fragments,
        inj_block=inj_block if placement == "pre_writer" else None,
        reasoning_on=reasoning_on,
        tool_schema=tool_schema,
    )

    if placement == "post_turn":
        # Replay the writer exchange so the call extends the warm writer/editor prefix.
        trailing: list[ChatMessage] = [
            {"role": "user", "content": writer_user_msg or ""},
            {"role": "assistant", "content": reply_text or ""},
            {"role": "user", "content": request},
        ]
    else:
        trailing = [{"role": "user", "content": request}]

    hyperparams = extract_hyperparams(settings, defaults={"temperature": 0.4, "max_tokens": 2048})

    resp: dict = {}
    try:
        async for event in base.complete(
            client,
            label="direction_note",
            trailing=trailing,
            tool_choice=RECORD_DIRECTION_NOTE_CHOICE,
            kv_tracker=kv_tracker,
            **hyperparams,
            **reasoning_cfg(reasoning_on),
        ):
            if event["type"] == "reasoning":
                yield {"type": "reasoning", "delta": event["delta"]}
            elif event["type"] == "done":
                resp = event["message"]
    except Exception:
        logger.exception("Direction-note step failed; recording nothing this turn")
        yield {"type": "done", "result": DirectionNoteResult()}
        return

    agent_raw = json.dumps(resp, default=str)
    logger.info("Direction-note step output:\n%s", agent_raw)
    notes = extract_direction_notes(parse_tool_calls(resp), direction_note_fragments)

    yield {"type": "done", "result": DirectionNoteResult(notes=notes, agent_raw=agent_raw)}
