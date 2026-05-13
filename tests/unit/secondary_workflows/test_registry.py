"""Unit tests for the workflow registry: registration, tool diff, name
collisions, iteration order, and the overlay_enable_tools helper."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from backend.secondary_workflows import (
    ToolNameCollision,
    Workflow,
    get_workflow,
    list_workflows,
    overlay_enable_tools,
    register_workflow,
)
from backend.secondary_workflows.contracts import ToolSpec
from backend.secondary_workflows import registry as registry_module
from backend.tool_defs import STANDALONE_TOOLS, TOOLS


def _tool_spec(name: str, *, standalone: bool = True) -> ToolSpec:
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": "test",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    choice = {"type": "function", "function": {"name": name}}
    return ToolSpec(name=name, schema=schema, choice=choice, standalone=standalone)


@pytest.fixture(autouse=True)
def _restore_globals():
    """Snapshot and restore the four mutable module-globals around each test."""
    workflows_snapshot = list(registry_module._WORKFLOWS)
    by_id_snapshot = dict(registry_module._WORKFLOWS_BY_ID)
    tools_snapshot = dict(TOOLS)
    standalone_snapshot = set(STANDALONE_TOOLS)
    yield
    registry_module._WORKFLOWS.clear()
    registry_module._WORKFLOWS.extend(workflows_snapshot)
    registry_module._WORKFLOWS_BY_ID.clear()
    registry_module._WORKFLOWS_BY_ID.update(by_id_snapshot)
    TOOLS.clear()
    TOOLS.update(tools_snapshot)
    STANDALONE_TOOLS.clear()
    STANDALONE_TOOLS.update(standalone_snapshot)


class TestFreshRegistration:
    def test_workflow_appears_in_list(self):
        register_workflow(Workflow(id="wf_a", display_name="A"))
        assert [w.id for w in list_workflows()] == ["wf_a"]

    def test_tool_lands_in_global_registry(self):
        spec = _tool_spec("wf_a_tool", standalone=True)
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[spec]))
        assert "wf_a_tool" in TOOLS
        assert "wf_a_tool" in STANDALONE_TOOLS

    def test_non_standalone_tool_omitted_from_standalone_set(self):
        spec = _tool_spec("wf_a_tool", standalone=False)
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[spec]))
        assert "wf_a_tool" in TOOLS
        assert "wf_a_tool" not in STANDALONE_TOOLS

    def test_get_workflow_returns_registered(self):
        w = Workflow(id="wf_a", display_name="A")
        register_workflow(w)
        assert get_workflow("wf_a") is w

    def test_get_workflow_missing(self):
        assert get_workflow("nope") is None


class TestReRegistration:
    def test_replace_in_place_keeps_list_length(self):
        register_workflow(Workflow(id="wf_a", display_name="A"))
        register_workflow(Workflow(id="wf_a", display_name="A v2"))
        wfs = list_workflows()
        assert len(wfs) == 1
        assert wfs[0].display_name == "A v2"

    def test_tool_diff_drop_removes_orphan(self):
        a = _tool_spec("ws_test_a")
        b = _tool_spec("ws_test_b")
        register_workflow(Workflow(id="ws_test", display_name="X", tools=[a, b]))
        assert "ws_test_a" in TOOLS and "ws_test_b" in TOOLS

        register_workflow(Workflow(id="ws_test", display_name="X", tools=[a]))
        assert "ws_test_a" in TOOLS
        assert "ws_test_b" not in TOOLS
        assert "ws_test_b" not in STANDALONE_TOOLS

    def test_tool_standalone_bit_toggles_symmetrically(self):
        spec_on = _tool_spec("wf_a_tool", standalone=True)
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[spec_on]))
        assert "wf_a_tool" in STANDALONE_TOOLS

        spec_off = _tool_spec("wf_a_tool", standalone=False)
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[spec_off]))
        assert "wf_a_tool" in TOOLS
        assert "wf_a_tool" not in STANDALONE_TOOLS


class TestBuiltinCollision:
    def test_raises_and_leaves_builtin_unchanged(self):
        before = TOOLS["editor_rewrite"]
        clash = _tool_spec("editor_rewrite")
        with pytest.raises(ToolNameCollision):
            register_workflow(Workflow(id="ws_clash", display_name="X", tools=[clash]))
        assert TOOLS["editor_rewrite"] is before
        assert get_workflow("ws_clash") is None

    def test_built_in_check_fires_before_cross_workflow_check(self):
        # Set up a workflow that legitimately owns a non-built-in tool.
        register_workflow(Workflow(id="wf_owner", display_name="O", tools=[_tool_spec("editor_rewrite_alt")]))
        # New workflow tries to claim a built-in name AND that name happens to
        # *also* live on another workflow's tools. The built-in check still
        # wins because it runs first.
        with pytest.raises(ToolNameCollision, match="built-in tool name"):
            register_workflow(Workflow(id="wf_other", display_name="X", tools=[_tool_spec("editor_rewrite")]))


class TestCrossWorkflowCollision:
    def test_two_workflows_cannot_share_tool(self):
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[_tool_spec("shared_tool")]))
        with pytest.raises(ToolNameCollision, match="owned by workflow 'wf_a'"):
            register_workflow(Workflow(id="wf_b", display_name="B", tools=[_tool_spec("shared_tool")]))
        assert get_workflow("wf_b") is None
        assert "shared_tool" in TOOLS

    def test_same_workflow_keeping_its_tool_no_collision(self):
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[_tool_spec("kept")]))
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[_tool_spec("kept")]))
        assert "kept" in TOOLS


class TestAtomicity:
    def test_rejected_registration_leaves_state_untouched(self):
        register_workflow(Workflow(id="wf_a", display_name="A", tools=[_tool_spec("kept")]))
        workflows_before = list(registry_module._WORKFLOWS)
        tools_before = dict(TOOLS)
        standalone_before = set(STANDALONE_TOOLS)

        clash = Workflow(
            id="wf_b",
            display_name="B",
            tools=[_tool_spec("kept"), _tool_spec("new_one")],
        )
        with pytest.raises(ToolNameCollision):
            register_workflow(clash)

        assert registry_module._WORKFLOWS == workflows_before
        assert TOOLS == tools_before
        assert STANDALONE_TOOLS == standalone_before
        assert "new_one" not in TOOLS


class TestIterationOrder:
    def test_priority_then_id(self):
        register_workflow(Workflow(id="c", display_name="C", priority=10))
        register_workflow(Workflow(id="b", display_name="B", priority=0))
        register_workflow(Workflow(id="a", display_name="A", priority=0))
        ids = [w.id for w in list_workflows()]
        assert ids == ["a", "b", "c"]

    def test_re_register_keeps_order_by_priority_id(self):
        register_workflow(Workflow(id="z", display_name="Z", priority=0))
        register_workflow(Workflow(id="m", display_name="M", priority=5))
        register_workflow(Workflow(id="m", display_name="M2", priority=-5))
        ids = [w.id for w in list_workflows()]
        assert ids == ["m", "z"]

    def test_list_returns_copy(self):
        register_workflow(Workflow(id="a", display_name="A"))
        wfs = list_workflows()
        wfs.append("not a workflow")  # type: ignore[arg-type]
        assert len(list_workflows()) == 1


class TestOverlayEnableTools:
    def test_none_contribution_returns_fresh_copy(self):
        base = {"x": True}
        out = overlay_enable_tools(base, None)
        assert out == base
        assert out is not base
        out["x"] = False
        assert base["x"] is True

    def test_set_contribution_enables_names(self):
        out = overlay_enable_tools({"x": False}, {"x", "y"})
        assert out == {"x": True, "y": True}

    def test_mapping_contribution_true_wins_false_ignored(self):
        out = overlay_enable_tools({"x": True, "y": False}, {"x": False, "y": True, "z": True})
        assert out == {"x": True, "y": True, "z": True}

    def test_accepts_mapping_proxy_base(self):
        base = MappingProxyType({"x": True})
        out = overlay_enable_tools(base, {"y"})
        assert isinstance(out, dict)
        assert out == {"x": True, "y": True}

    def test_empty_set_no_change(self):
        out = overlay_enable_tools({"x": True}, set())
        assert out == {"x": True}

    def test_frozenset_contribution(self):
        out = overlay_enable_tools({}, frozenset({"a", "b"}))
        assert out == {"a": True, "b": True}
