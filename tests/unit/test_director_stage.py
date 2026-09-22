"""director_stage: the lorebook pick runs before the scene-direction steps.

Covers the order of the forced calls, the lore each ``direct_scene`` step is
shown, the event sequence the status bar relies on, and the stop path.
"""

from __future__ import annotations

import json

from backend.core import Macros
from backend.inference import CachedBase, _KVCacheTracker
from backend.pipeline.passes.director import director_stage
from backend.pipeline.state import LorebookTurn, ModelLane, TurnState, _PipelineConfig
from backend.prompting.tool_schemas import SELECT_LOREBOOK_TOOL, build_direct_scene_tool

_FRAGMENTS = [
    {
        "id": "user_intent",
        "field_type": "string",
        "description": "what the user wants",
        "injection_label": "User intent",
        "sort_order": 1,
    },
    {
        "id": "next_event",
        "field_type": "string",
        "description": "what happens next",
        "injection_label": "Next event",
        "sort_order": 2,
    },
]
_USER_MESSAGE = "the user message"


def _entry(name: str) -> dict:
    return {"name": name, "content": f"{name} content", "keywords": [], "constant": False, "priority": 100}


_ENTRIES = [_entry("Dragon"), _entry("Castle")]
_KEYWORD_BLOCK = "**Lorebook**\n\nCastle: Castle content"


class _FakeClient:
    def __init__(self) -> None:
        self.is_aborted = False

    def abort(self) -> None:
        self.is_aborted = True


class _FakeBase:
    """Stands in for ``CachedBase``: answers each forced call by tool name and
    records the per-call label and request tail. ``complete_into`` is borrowed
    from the real class so the stage's event demux under test is the shipped one.
    """

    complete_into = CachedBase.complete_into

    def __init__(self, *, picks: list[str], abort_on_pick: bool = False):
        self.tools = [build_direct_scene_tool(_FRAGMENTS), SELECT_LOREBOOK_TOOL]
        self.prefix: list = []
        self.calls: list[tuple[str, str]] = []
        self._picks = picks
        self._abort_on_pick = abort_on_pick

    async def complete(self, client, *, label, trailing, tool_choice, **_):
        self.calls.append((label, trailing[0]["content"]))
        name = tool_choice["function"]["name"]
        if name == "select_lorebook":
            args: dict = {"selected_lorebook_entries": self._picks}
            if self._abort_on_pick:
                client.abort()
        else:
            args = {"user_intent": "wants X", "next_event": "she leaves", "moods": []}
        message = {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": json.dumps(args)}}]}
        yield {"type": "done", "message": message}


def _cfg(base: _FakeBase, client: _FakeClient, *, direct_scene: bool) -> _PipelineConfig:
    lane = ModelLane(client=client, base=base)  # type: ignore[arg-type]
    return _PipelineConfig(
        agent_on=True,
        enabled_tools={"direct_scene": direct_scene, "select_lorebook": True},
        director_reasoning_on=False,
        writer_reasoning_on=False,
        editor_reasoning_on=False,
        director_reasoning_prefill="",
        writer_reasoning_prefill="",
        editor_reasoning_prefill="",
        audit_enabled=False,
        length_guard=None,
        do_edit=False,
        writer_lane=lane,
        agent_lane=lane,
    )


async def _run(base: _FakeBase, client: _FakeClient, *, agentic: bool = True, direct_scene: bool = True):
    state = TurnState(user_message=_USER_MESSAGE, effective_msg=_USER_MESSAGE, active_moods=[])
    lorebook = LorebookTurn(
        entries=_ENTRIES,
        messages=[{"role": "user", "content": _USER_MESSAGE}],
        agentic=agentic,
        block="" if agentic else _KEYWORD_BLOCK,
        catalog="- [Dragon]\n- [Castle]" if agentic else "",
    )
    events = [
        event
        async for event in director_stage(
            _cfg(base, client, direct_scene=direct_scene),
            state,
            settings={"director_individual_fragments": 1},
            director={"active_moods": []},
            mood_fragments=[],
            writer_fragments=_FRAGMENTS,
            attachments=[],
            kv_tracker=_KVCacheTracker(),
            lorebook=lorebook,
            macros=Macros("User", ""),
        )
    ]
    return state, events


def _phase_events(events: list[dict]) -> list[tuple[str, str | None]]:
    return [
        (event["event"], (event.get("data") or {}).get("step"))
        for event in events
        if event["event"] in ("director_start", "step_start", "director_done")
    ]


async def test_pick_runs_first_and_every_scene_step_sees_the_picked_lore():
    base = _FakeBase(picks=["Dragon"])
    state, events = await _run(base, _FakeClient())

    # One pick, then one direct_scene call per fragment plus the moods call.
    assert [label for label, _ in base.calls] == ["select_lorebook"] + ["director:direct_scene"] * 3
    scene_tails = [tail for _, tail in base.calls[1:]]
    assert state.writer_lorebook_block == "**Lorebook**\n\nDragon: Dragon content"
    assert all(state.writer_lorebook_block in tail for tail in scene_tails)
    assert not any("Castle" in tail for tail in scene_tails)
    # The recorded calls keep execution order, so the pick leads the inspector's list.
    assert [call["name"] for call in state.calls] == ["select_lorebook"] + ["direct_scene"] * 3
    assert _phase_events(events) == [
        ("director_start", None),
        ("step_start", "lorebook"),
        ("step_start", "director"),
        ("director_done", None),
    ]


async def test_keyword_mode_hands_the_director_the_keyword_block():
    base = _FakeBase(picks=["Dragon"])
    state, events = await _run(base, _FakeClient(), agentic=False)

    assert [label for label, _ in base.calls] == ["director:direct_scene"] * 3
    assert all(_KEYWORD_BLOCK in tail for _, tail in base.calls)
    assert state.writer_lorebook_block == _KEYWORD_BLOCK
    # No lorebook step, so no relabel either.
    assert _phase_events(events) == [("director_start", None), ("director_done", None)]


async def test_pick_without_scene_direction_emits_no_director_step():
    base = _FakeBase(picks=["Dragon"])
    state, events = await _run(base, _FakeClient(), direct_scene=False)

    assert [label for label, _ in base.calls] == ["select_lorebook"]
    assert state.writer_lorebook_block == "**Lorebook**\n\nDragon: Dragon content"
    assert _phase_events(events) == [("step_start", "lorebook"), ("director_done", None)]


async def test_stop_during_the_pick_skips_the_director_pass():
    base = _FakeBase(picks=["Dragon"], abort_on_pick=True)
    state, events = await _run(base, _FakeClient())

    assert [label for label, _ in base.calls] == ["select_lorebook"]
    assert state.selected_lorebook_entries == ["Dragon"]
    assert _phase_events(events) == [("director_start", None), ("step_start", "lorebook")]
