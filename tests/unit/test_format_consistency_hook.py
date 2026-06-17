"""Unit tests for the format_consistency workflow's post_pipeline hook.

These stay true unit tests (no DB, no Codex-sandbox aiosqlite caveat) by
monkeypatching ``get_workflow_config`` as imported into the hook module. The
pure normalizer it calls is covered exhaustively by
``tests/unit/test_format_consistency.py``; here we only pin the hook's wiring:
the config gate, the baseline reconstructed from ``ctx.history``, and the
``draft_replaced`` event shape.
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


def _patch_cfg(monkeypatch, enabled: bool) -> None:
    async def fake_get_workflow_config(workflow_id):
        return {"enabled": enabled}

    monkeypatch.setattr(hooks, "get_workflow_config", fake_get_workflow_config)


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


async def test_yields_draft_replaced_on_drift(monkeypatch):
    _patch_cfg(monkeypatch, True)
    # A user message is interleaved to confirm the baseline window skips it.
    history = [
        {"role": "assistant", "content": QUOTED_BASELINE},
        {"role": "user", "content": "and then?"},
    ]
    events = await _collect(_ctx(DRIFTING_DRAFT, history))

    assert events == [{"type": "draft_replaced", "draft": NORMALIZED}]


async def test_no_yield_when_disabled(monkeypatch):
    # Same drifting draft, but the config gate is off -> the hook returns before
    # touching the normalizer.
    _patch_cfg(monkeypatch, False)
    history = [{"role": "assistant", "content": QUOTED_BASELINE}]
    events = await _collect(_ctx(DRIFTING_DRAFT, history))

    assert events == []


async def test_no_yield_when_baseline_unstable(monkeypatch):
    _patch_cfg(monkeypatch, True)
    # Two assistant messages with conflicting conventions -> neither axis agrees.
    history = [
        {"role": "assistant", "content": QUOTED_BASELINE},
        {"role": "assistant", "content": ASTERISK_MSG},
    ]
    events = await _collect(_ctx('She frowns. "What now?"', history))

    assert events == []


async def test_no_yield_when_already_consistent(monkeypatch):
    _patch_cfg(monkeypatch, True)
    history = [{"role": "assistant", "content": QUOTED_BASELINE}]
    events = await _collect(_ctx(CONSISTENT_DRAFT, history))

    assert events == []


async def test_no_yield_when_no_assistant_baseline(monkeypatch):
    _patch_cfg(monkeypatch, True)
    # Only user messages: the window is empty, so the normalizer no-ops.
    history = [{"role": "user", "content": "hello"}]
    events = await _collect(_ctx(DRIFTING_DRAFT, history))

    assert events == []
