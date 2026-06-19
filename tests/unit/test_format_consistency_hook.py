"""Unit tests for the format_consistency workflow's post_pipeline hook.

These stay true unit tests (no DB, no Codex-sandbox aiosqlite caveat). The pure
normalizer the hook calls is covered exhaustively by
``tests/unit/test_format_consistency.py``; here we pin the hook's wiring: the
baseline reconstructed from ``ctx.history`` and the ``draft_replaced`` event
shape. The on/off decision is no longer the hook's concern -- the framework's
per-workflow toggle suspends it in the fan-out loop -- so the hook always runs
when reached, and there is no config gate to patch.
"""

from __future__ import annotations

from types import MappingProxyType

from backend.workflows import PostCtx
from backend.workflows.format_consistency import hooks

# A single QUOTED-convention baseline; an asterisk-narration draft drifts from it
# and is rewritten (lifted from the pure-logic suite's inversion case).
QUOTED_BASELINE = 'She smiles. "Hello there," she says warmly.'
DRIFTING_DRAFT = "*She steps closer, watching him carefully.* Are you sure about this?"
NORMALIZED = 'She steps closer, watching him carefully. "Are you sure about this?"'
CONSISTENT_DRAFT = 'He nods slowly. "I understand," he replies.'

# Conflicting conventions in the window -> no axis agrees -> nothing to enforce.
ASTERISK_MSG = "*She smiles and steps back, turning to the window.* I won't go."


def _ctx(draft: str, history: list[dict]) -> PostCtx:
    return PostCtx(
        conversation_id="c1",
        history=tuple(MappingProxyType(m) for m in history),
        draft=draft,
        effective_msg="",
        director_output=MappingProxyType({}),
        settings=MappingProxyType({}),
        prefix=(),
        enabled_tools=MappingProxyType({}),
        turn_scratch={},
        client=None,
        kv_tracker=None,
        schema_overrides=MappingProxyType({}),
        character_id=None,
    )


async def _collect(ctx) -> list[dict]:
    return [ev async for ev in hooks.post_pipeline(ctx)]


async def test_yields_draft_replaced_on_drift():
    # No config patch: the hook runs unconditionally now (the framework toggle is
    # the only on/off). A user message is interleaved to confirm the baseline
    # window skips it.
    history = [
        {"role": "assistant", "content": QUOTED_BASELINE},
        {"role": "user", "content": "and then?"},
    ]
    events = await _collect(_ctx(DRIFTING_DRAFT, history))

    assert events == [{"type": "draft_replaced", "draft": NORMALIZED}]


async def test_no_yield_when_baseline_unstable():
    # Two assistant messages with conflicting conventions -> neither axis agrees.
    history = [
        {"role": "assistant", "content": QUOTED_BASELINE},
        {"role": "assistant", "content": ASTERISK_MSG},
    ]
    events = await _collect(_ctx('She frowns. "What now?"', history))

    assert events == []


async def test_no_yield_when_already_consistent():
    history = [{"role": "assistant", "content": QUOTED_BASELINE}]
    events = await _collect(_ctx(CONSISTENT_DRAFT, history))

    assert events == []


async def test_no_yield_when_no_assistant_baseline():
    # Only user messages: the window is empty, so the normalizer no-ops.
    history = [{"role": "user", "content": "hello"}]
    events = await _collect(_ctx(DRIFTING_DRAFT, history))

    assert events == []
