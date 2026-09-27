"""Choose a group exchange's speakers before any of them is directed."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ....core import build_multimodal_content, extract_hyperparams
from ....inference import (
    CachedBase,
    LLMClient,
    _KVCacheTracker,
    parse_tool_calls,
    reasoning_cfg,
)
from ....prompting.tool_catalog import require_tool
from ...predicates import direction_note_to_director
from .direction_note_prompts import render_direction_notes_block
from .director import (
    SPEAKING_PLAN_FIELD,
    SPEAKING_PLAN_STAGE,
    _step_schema,
    keeps_director_value,
    speaking_plan_instruction,
)
from .prompts import build_director_scene_step_prompt

if TYPE_CHECKING:
    from ....core import Macros
    from ...state import LorebookTurn

logger = logging.getLogger(__name__)


async def speaking_plan_step(
    client: LLMClient,
    base: CachedBase,
    *,
    settings: Mapping[str, Any],
    user_message: str,
    attachments: Sequence[Mapping[str, Any]],
    speaker_keys: str,
    lorebook: LorebookTurn,
    direction_notes: Sequence[Mapping[str, Any]],
    macros: Macros,
    kv_tracker: _KVCacheTracker | None = None,
    reasoning_on: bool = False,
    reasoning_prefill: str = "",
) -> AsyncIterator[dict]:
    """Yield reasoning chunks during one forced call, then a single done dict.

    The per-fragment Director's speaking-plan step on its own: the same request
    and the same single-field schema, so the plan exists before each speaker's
    own Director run.

    Yields:
        ``{"type": "reasoning", "delta": str}``
        ``{"type": "done", "plan": list | None}`` -- None when no plan came back
    """
    tool_schema = next((s for s in base.tools if s["function"]["name"] == "direct_scene"), None)
    step_schema = _step_schema(tool_schema, SPEAKING_PLAN_FIELD) if tool_schema else None
    if not speaker_keys or step_schema is None:
        yield {"type": "done", "plan": None}
        return

    lorebook_block = lorebook.writer_block((), macros)
    notes_block = (
        macros.resolve_message(render_direction_notes_block(direction_notes))
        if direction_notes and direction_note_to_director(settings)
        else ""
    )
    request = build_director_scene_step_prompt(
        user_message,
        [],
        [],
        tool_schema=tool_schema,
        reasoning_on=reasoning_on,
        target_fragment=SPEAKING_PLAN_STAGE,
        cast_instruction=speaking_plan_instruction(speaker_keys),
    )
    fenced = "".join(f"___\n\n{block}\n\n" for block in (lorebook_block, notes_block) if block)
    trailing = [{"role": "user", "content": build_multimodal_content(fenced + request, attachments)}]

    resp: dict = {}
    try:
        async for event in base.complete_into(
            client,
            resp,
            label="director:speaking_plan",
            trailing=trailing,
            tool_choice=require_tool("direct_scene")["choice"],
            kv_tracker=kv_tracker,
            json_schema=step_schema,
            **extract_hyperparams(settings, lane="agent", defaults={"temperature": 0.25}),
            **reasoning_cfg(reasoning_on, reasoning_prefill),
        ):
            yield event
    except Exception:
        # No plan is not a failed exchange: the driver falls back to round-robin.
        logger.exception("Speaking-plan call failed; no plan this exchange")
        yield {"type": "done", "plan": None}
        return

    logger.info("Speaking-plan step output:\n%s", json.dumps(resp, default=str))
    calls = parse_tool_calls(resp, fields=[SPEAKING_PLAN_FIELD])
    args = next((tc.get("arguments", {}) for tc in calls if tc.get("name") == "direct_scene"), {})
    plan = args.get(SPEAKING_PLAN_FIELD)
    yield {"type": "done", "plan": plan if keeps_director_value(SPEAKING_PLAN_FIELD, plan) else None}
