"""Unit tests for the tool registry surface: built-in name set, register_tool,
standalone filter, and enabled_schemas ordering."""

from __future__ import annotations

import pytest

from backend.tool_defs import (
    BUILTIN_TOOL_NAMES,
    STANDALONE_TOOLS,
    TOOLS,
    enabled_schemas,
    register_tool,
)
from backend.kv_tracker import _KVCacheTracker


_TEST_TOOL_NAME = "ut_tool_defs_test"
_TEST_SCHEMA = {
    "type": "function",
    "function": {
        "name": _TEST_TOOL_NAME,
        "description": "test",
        "parameters": {"type": "object", "properties": {}},
    },
}
_TEST_CHOICE = {"type": "function", "function": {"name": _TEST_TOOL_NAME}}


@pytest.fixture
def _restore_registry():
    """Restore TOOLS and STANDALONE_TOOLS after a test mutates them."""
    tools_snapshot = dict(TOOLS)
    standalone_snapshot = set(STANDALONE_TOOLS)
    yield
    TOOLS.clear()
    TOOLS.update(tools_snapshot)
    STANDALONE_TOOLS.clear()
    STANDALONE_TOOLS.update(standalone_snapshot)


class TestBuiltinToolNames:
    def test_matches_tools_keys_at_module_load(self):
        assert BUILTIN_TOOL_NAMES == frozenset(TOOLS.keys())

    def test_is_a_frozenset(self):
        assert isinstance(BUILTIN_TOOL_NAMES, frozenset)


class TestStandaloneToolsBaseline:
    def test_empty_at_module_load(self):
        assert STANDALONE_TOOLS == set()


class TestEnabledSchemasBaseline:
    def test_none_returns_all_built_in_schemas(self):
        schemas = enabled_schemas(None)
        names = [s["function"]["name"] for s in schemas]
        assert set(names) == BUILTIN_TOOL_NAMES

    def test_none_returns_alphabetical_order(self):
        schemas = enabled_schemas(None)
        names = [s["function"]["name"] for s in schemas]
        assert names == sorted(names)
        assert names == [
            "direct_scene",
            "editor_apply_patch",
            "editor_rewrite",
            "rewrite_user_prompt",
        ]

    def test_dict_filter_returns_alphabetical_subset(self):
        gated = {"editor_rewrite": True, "direct_scene": True, "editor_apply_patch": False}
        names = [s["function"]["name"] for s in enabled_schemas(gated)]
        assert names == ["direct_scene", "editor_rewrite"]

    def test_empty_dict_returns_nothing(self):
        assert enabled_schemas({}) == []


class TestRegisterTool:
    def test_standalone_true_filters_out_of_schemas(self, _restore_registry):
        register_tool(_TEST_TOOL_NAME, _TEST_SCHEMA, _TEST_CHOICE, standalone=True)
        assert _TEST_TOOL_NAME in TOOLS
        assert _TEST_TOOL_NAME in STANDALONE_TOOLS
        names = [s["function"]["name"] for s in enabled_schemas(None)]
        assert _TEST_TOOL_NAME not in names

    def test_standalone_false_appears_in_schemas(self, _restore_registry):
        register_tool(_TEST_TOOL_NAME, _TEST_SCHEMA, _TEST_CHOICE, standalone=False)
        assert _TEST_TOOL_NAME in TOOLS
        assert _TEST_TOOL_NAME not in STANDALONE_TOOLS
        names = [s["function"]["name"] for s in enabled_schemas(None)]
        assert _TEST_TOOL_NAME in names

    def test_standalone_bit_symmetric_on_reregistration(self, _restore_registry):
        register_tool(_TEST_TOOL_NAME, _TEST_SCHEMA, _TEST_CHOICE, standalone=True)
        assert _TEST_TOOL_NAME in STANDALONE_TOOLS

        register_tool(_TEST_TOOL_NAME, _TEST_SCHEMA, _TEST_CHOICE, standalone=False)
        assert _TEST_TOOL_NAME not in STANDALONE_TOOLS

        register_tool(_TEST_TOOL_NAME, _TEST_SCHEMA, _TEST_CHOICE, standalone=True)
        assert _TEST_TOOL_NAME in STANDALONE_TOOLS

    def test_alphabetical_order_holds_with_workflow_tool(self, _restore_registry):
        register_tool(
            "aaa_first",
            {"type": "function", "function": {"name": "aaa_first"}},
            {"type": "function", "function": {"name": "aaa_first"}},
            standalone=False,
        )
        names = [s["function"]["name"] for s in enabled_schemas(None)]
        assert names[0] == "aaa_first"
        assert names[1:] == sorted(names[1:])


class TestKVTrackerPrefixChars:
    def test_default_prefix_chars_zero(self):
        kv = _KVCacheTracker()
        assert kv._prefix_chars == 0

    def test_set_prefix_chars_updates_value(self):
        kv = _KVCacheTracker()
        kv.set_prefix_chars(12345)
        assert kv._prefix_chars == 12345

    def test_init_kwarg_sets_value(self):
        kv = _KVCacheTracker(prefix_chars=999)
        assert kv._prefix_chars == 999

    def test_log_summary_tail_uses_prefix_chars(self, caplog):
        kv = _KVCacheTracker()
        kv.record("a", [{"role": "user", "content": "hello world"}], None, model="m")
        kv.set_prefix_chars(5)
        with caplog.at_level("INFO", logger="backend.kv_tracker"):
            kv.log_summary()
        total = kv._entries[0]["total_chars"]
        assert f"total={total:7d}  tail={total - 5:6d}" in caplog.text
