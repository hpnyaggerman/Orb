"""
orchestrator.py — Sequences the three passes for one turn.

:func:`_run_pipeline` resolves the per-turn config, threads a mutable
:class:`TurnState` through the director, writer, and editor stages, runs
POST_PIPELINE workflow hooks, and emits the terminal ``_result`` event.

Context loading lives in ``context``, persistence in ``persistence``, and the
public entry points in ``entrypoints``. ``_run_pipeline`` is called by
``_generate_reply`` (and directly by tests).
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Mapping, Optional, Sequence

from ..core import ChatMessage, Macros
from ..database.models import PhraseGroup
from ..inference import LLMClient, _KVCacheTracker
from .config import _resolve_pipeline_config, _split_interactive_fragments
from .passes.director import director_stage
from .passes.editor import editor_stage
from .passes.writer import writer_stage
from .state import TurnState
from .workflow_bridge import _PostPipelineResult, _run_post_pipeline

logger = logging.getLogger(__name__)


# ── Core pipeline ─────────────────────────────────────────────────────────────


def _make_result(state: TurnState, staged: list[dict] | None = None, staged_state: dict | None = None) -> dict:
    """Build the terminal ``_result`` SSE event from *state*.

    *staged* / *staged_state* are workflow attachments and per-message state
    produced by post-pipeline hooks; they are folded onto *state* before
    serialization so the whole result travels as one object.
    """
    state.staged_attachments = staged or []
    state.staged_message_state = staged_state or {}
    return {"event": "_result", "data": state.as_result_event_data()}


async def _run_pipeline(
    client: LLMClient,
    settings: Mapping[str, Any],
    director: Mapping[str, Any],
    mood_fragments: Sequence[Mapping[str, Any]],
    interactive_fragments: Sequence[Mapping[str, Any]],
    user_message: str,
    attachments: Optional[Sequence[Mapping[str, Any]]] = None,
    phrase_bank: list[PhraseGroup] | None = None,
    lorebook_block: str = "",
    lorebook_catalog: str = "",
    agentic_lorebook: bool = False,
    lorebook_entries: Sequence[Mapping[str, Any]] | None = None,
    editor_audit_msgs: list[str] | None = None,
    agent_client: LLMClient | None = None,
    agent_prefix: list[ChatMessage] | None = None,
    macros: Macros | None = None,
    conversation_id: str | None = None,
    character_id: str | None = None,
    card: Mapping[str, Any] | None = None,
    *,
    prefix: list[ChatMessage],
    enabled_tools: Mapping[str, bool],
    turn_scratch: dict,
    kv_tracker: _KVCacheTracker,
    schema_overrides: Mapping[str, dict],
    history: Sequence[Mapping[str, Any]] | None = None,
    lorebook_messages: Sequence[Mapping[str, Any]] | None = None,
) -> AsyncIterator[dict]:
    """Run the director → writer → editor passes for one turn.

    Streams SSE events as each pass runs, then runs post-pipeline workflow
    hooks and emits a single ``_result`` event with the final draft and any
    workflow attachments.

    A stop during the director pass exits cleanly with no output. A stop during
    the writer pass still emits ``_result`` with the partial draft so persistence
    can save it.
    """
    if macros is None:
        macros = Macros("User", "")
    if attachments is None:
        attachments = []

    user_message = macros.resolve_message(user_message)

    # Resolved once; cfg.enabled_tools is the length-guard-folded map.
    cfg = _resolve_pipeline_config(
        settings,
        enabled_tools,
        macros=macros,
        client=client,
        agent_client=agent_client,
        agent_prefix=agent_prefix,
        prefix=prefix,
        phrase_bank=phrase_bank,
        schema_overrides=schema_overrides,
    )

    # feedback fragments are handled post-writer; the rest shape the writer prompt.
    writer_fragments, feedback_fragments = _split_interactive_fragments(interactive_fragments)

    # Mutable state threaded through the three passes; seeded from director + user message.
    state = TurnState(
        user_message=user_message,
        effective_msg=user_message,
        active_moods=director["active_moods"],
    )

    # --- Director pass (+ rewrite, style injection, agentic-lorebook block) ---
    async for ev in director_stage(
        cfg,
        state,
        settings=settings,
        director=director,
        mood_fragments=mood_fragments,
        writer_fragments=writer_fragments,
        attachments=attachments,
        kv_tracker=kv_tracker,
        lorebook_block=lorebook_block,
        lorebook_catalog=lorebook_catalog,
        lorebook_entries=lorebook_entries,
        lorebook_messages=lorebook_messages,
        agentic_lorebook=agentic_lorebook,
        macros=macros,
    ):
        yield ev

    # Both clients share one abort token, so checking either is equivalent.
    if client.is_aborted:
        return

    # --- Writer pass ---
    async for ev in writer_stage(
        cfg,
        state,
        settings=settings,
        attachments=attachments,
        kv_tracker=kv_tracker,
    ):
        yield ev

    # Aborted mid-writer: persist partial output and skip remaining passes.
    if client.is_aborted:
        yield _make_result(state)
        kv_tracker.log_summary()
        return

    # --- Editor pass (edit loop + post-writer feedback step) ---
    async for ev in editor_stage(
        cfg,
        state,
        settings=settings,
        phrase_bank=phrase_bank,
        feedback_fragments=feedback_fragments,
        editor_audit_msgs=editor_audit_msgs,
        kv_tracker=kv_tracker,
    ):
        yield ev

    # --- Post-pipeline workflow iteration ---
    # director_output is a plain dict (PostCtx expects a read-only mapping).
    director_output = state.as_director_output()
    post: _PostPipelineResult | None = None
    async for ev in _run_post_pipeline(
        draft=state.resp_text,
        conversation_id=conversation_id,
        character_id=character_id,
        card=card,
        history=history,
        effective_msg=state.effective_msg,
        director_output=director_output,
        settings=settings,
        prefix=prefix,
        enabled_tools=cfg.enabled_tools,
        turn_scratch=turn_scratch,
        client=client,
        kv_tracker=kv_tracker,
        schema_overrides=schema_overrides,
    ):
        if isinstance(ev, _PostPipelineResult):
            post = ev
        else:
            yield ev
    assert post is not None

    # Fold any hook-rewritten draft back into state before emitting _result.
    state.resp_text = post.draft
    yield _make_result(state, post.staged_attachments, post.staged_message_state)
    kv_tracker.log_summary()
