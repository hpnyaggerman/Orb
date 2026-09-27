"""{{char}} in the fragment descriptions a group's Director reads.

A Director run for one group speaker names that speaker wherever it reads a
description; the shared direct_scene schema, which rides every speaker's cached
prompt, words it neutrally in that mode and names the group otherwise.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from backend.core import Macros
from backend.inference import CachedBase
from backend.pipeline.config import _build_writer_tools_blob
from backend.pipeline.passes.director import (
    build_direct_scene_override,
    speaking_plan_step,
)
from backend.pipeline.passes.director.director import director_pass
from backend.pipeline.state import LorebookTurn
from backend.prompting import SPEAKING_CHARACTER, resolve_char_in_descriptions

_MOODS = [{"id": "cornered", "description": "{{char}} is cornered"}]
_FRAGMENTS = [
    {"id": "goal", "field_type": "string", "description": "What {{char}} wants", "injection_label": "Goal", "sort_order": 1},
    {"id": "pacing", "field_type": "string", "description": "scene pacing", "injection_label": "Pacing", "sort_order": 2},
]


def _ds_message(args: dict) -> dict:
    return {"role": "assistant", "tool_calls": [{"function": {"name": "direct_scene", "arguments": json.dumps(args)}}]}


class _FakeBase:
    """Serves canned completions over a group's direct_scene schema and records each request."""

    complete_into = CachedBase.complete_into

    def __init__(self, responses: Sequence[dict | None]):
        self.tools = [build_direct_scene_override(_FRAGMENTS, grouped=True)]
        self.prefix: list = []
        self._responses = list(responses)
        self.requests: list[str] = []
        self.schemas: list[dict | None] = []

    async def complete(self, *_, trailing, **kw):
        self.requests.append(trailing[0]["content"])
        self.schemas.append(kw.get("json_schema"))
        response = self._responses.pop(0)
        if response is None:
            raise RuntimeError("boom")
        yield {"type": "done", "message": response}


class _FakeClient:
    is_aborted = False


async def _direct(base: _FakeBase, settings: dict, speaker_name: str = ""):
    events = [
        e
        async for e in director_pass(
            _FakeClient(),  # type: ignore[arg-type]
            base,  # type: ignore[arg-type]
            "the user message",
            settings,
            {"active_moods": []},
            _MOODS,
            _FRAGMENTS,
            {"direct_scene": True},
            speaker_name=speaker_name,
        )
    ]
    return events[-1]["result"]


async def _plan(base: _FakeBase, speaker_keys: str = "aria, kael"):
    events = [
        e
        async for e in speaking_plan_step(
            _FakeClient(),  # type: ignore[arg-type]
            base,  # type: ignore[arg-type]
            settings={},
            user_message="the user message",
            attachments=[],
            speaker_keys=speaker_keys,
            lorebook=LorebookTurn(entries=(), messages=(), agentic=False),
            direction_notes=[],
            macros=Macros("User", "Campfire"),
        )
    ]
    return events[-1]["plan"]


class TestResolveCharInDescriptions:
    def test_fills_char_in_any_case_and_leaves_other_macros(self):
        [out] = resolve_char_in_descriptions(
            [{"id": "a", "description": "{{char}} and {{CHAR}} meet {{user}} of {{cast}}"}], "Aria"
        )
        assert out["description"] == "Aria and Aria meet {{user}} of {{cast}}"

    def test_backticked_macro_stays_literal(self):
        [out] = resolve_char_in_descriptions([{"id": "a", "description": "`{{char}}` means {{char}}"}], "Aria")
        assert out["description"] == "`{{char}}` means Aria"

    def test_returns_copies(self):
        rows = [{"id": "a", "description": "{{char}}", "injection_label": "A"}]
        [out] = resolve_char_in_descriptions(rows, "Aria")
        assert rows[0]["description"] == "{{char}}"
        assert out == {"id": "a", "description": "Aria", "injection_label": "A"}

    def test_empty_name_leaves_the_macro(self):
        [out] = resolve_char_in_descriptions([{"id": "a", "description": "{{char}}"}], "")
        assert out["description"] == "{{char}}"


class TestSchemaChar:
    _OTHERS = [
        {"id": "fb", "field_type": "feedback", "description": "Tell {{char}}", "injection_label": "FB", "sort_order": 3},
        {
            "id": "dn",
            "field_type": "direction_note",
            "description": "About {{char}}",
            "injection_label": "DN",
            "sort_order": 4,
            "direction_note_timing": "post_turn",
        },
    ]

    def _blob(self, schema_char: str) -> dict:
        settings = {"feedback_enabled": 1, "direction_notes_record": 1}
        return _build_writer_tools_blob(settings, [*_FRAGMENTS, *self._OTHERS], {}, grouped=True, schema_char=schema_char)

    @staticmethod
    def _description(blob: dict, tool: str, field: str) -> str:
        return blob[tool]["function"]["parameters"]["properties"][field]["description"]

    def test_direct_scene_takes_the_schema_char(self):
        assert self._description(self._blob("Campfire"), "direct_scene", "goal") == "What Campfire wants"
        assert self._description(self._blob(SPEAKING_CHARACTER), "direct_scene", "goal") == "What the speaking character wants"

    def test_without_a_schema_char_the_macro_stays(self):
        assert self._description(self._blob(""), "direct_scene", "goal") == "What {{char}} wants"

    def test_other_fragment_schemas_keep_their_descriptions(self):
        blob = self._blob("Campfire")
        assert self._description(blob, "give_feedback", "fb") == "Tell {{char}}"
        assert self._description(blob, "record_direction_note", "dn") == "About {{char}}"


class TestSpeakerRun:
    async def test_per_fragment_steps_name_the_speaker_and_do_not_plan(self):
        responses = [_ds_message({"goal": "x"}), _ds_message({"pacing": "slow"}), _ds_message({"moods": []})]
        base = _FakeBase(responses)
        await _direct(base, {"director_individual_fragments": 1}, speaker_name="Aria")
        # The group schema offers a speaking plan, but a run for one speaker never plans.
        assert len(base.requests) == 3
        assert "What Aria wants" in base.requests[0]
        assert "Aria is cornered" in base.requests[-1]
        assert not any("{{char}}" in request for request in base.requests)

    async def test_the_exchange_run_still_plans(self):
        responses = [_ds_message({}), _ds_message({}), _ds_message({"speaking_plan": []}), _ds_message({})]
        base = _FakeBase(responses)
        result = await _direct(base, {"director_individual_fragments": 1})
        assert len(base.requests) == 4
        assert result.extra_fields == {"speaking_plan": []}

    async def test_one_call_request_restates_the_descriptions_that_name_the_speaker(self):
        base = _FakeBase([_ds_message({"goal": "x"})])
        await _direct(base, {}, speaker_name="Aria")
        request = base.requests[0]
        assert "* [goal] What Aria wants" in request
        assert "* [pacing]" not in request
        assert "Aria is cornered" in request

    async def test_one_call_request_without_a_speaker_is_unchanged(self):
        base = _FakeBase([_ds_message({"goal": "x"})])
        await _direct(base, {})
        request = base.requests[0]
        assert "Field descriptions for this reply" not in request
        # Resolved at send time, as before.
        assert "{{char}} is cornered" in request


class TestSpeakingPlanStep:
    async def test_returns_the_plan_from_one_narrowed_call(self):
        base = _FakeBase([_ds_message({"speaking_plan": ["aria - go"], "goal": "x"})])
        assert await _plan(base) == ["aria - go"]
        assert len(base.requests) == 1
        assert "aria, kael" in base.requests[0]
        assert list((base.schemas[0] or {})["properties"]) == ["speaking_plan"]

    async def test_an_intentional_rest_is_kept(self):
        assert await _plan(_FakeBase([_ds_message({"speaking_plan": []})])) == []

    async def test_no_castable_speaker_means_no_call(self):
        base = _FakeBase([])
        assert await _plan(base, speaker_keys="") is None
        assert base.requests == []

    async def test_a_failed_call_yields_no_plan(self):
        assert await _plan(_FakeBase([None])) is None
