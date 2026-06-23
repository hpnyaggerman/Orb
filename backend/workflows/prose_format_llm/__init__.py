"""LLM prose-format workflow.

Enforces a conversation's prose-markup convention (how narration, speech, etc.
are delimited) on the writer's finished draft, using three forced-tool LLM
paths: an analyzer that records the convention, a judge that locates
violations, and an enforcer that patches them. It does the same job as the
deterministic ``format_consistency`` workflow but covers the open-ended
violation space regex cannot; deploy it as a replacement by toggling
``format_consistency`` off.

This module is the data surface only -- constants, the tool schemas, and the
``Workflow`` record. The hooks, loop, and pure helpers live in sibling modules
and import these names back; keeping registration out of here avoids an import
cycle with ``backend/workflows/__init__.py``.
"""

from __future__ import annotations

from ..contracts import ToolSpec
from ..registry import Workflow

WORKFLOW_ID = "prose_format_llm"

TOOL_ANALYZE = "prose_format_analyze"
TOOL_REPORT = "prose_format_report"
TOOL_PATCH = "prose_format_patch"

# Seeded into each conversation's state. Values are guidance FOR the analyzer --
# they describe what to record about each element, and are never themselves used
# to judge a draft. The analyzer overwrites the parallel ``values`` map with the
# convention it observes; until it does, the conversation is unarmed and the
# loop stays dormant.
DEFAULT_SCHEMA = {
    "narration": "How narration is denoted (e.g. text wrapped in asterisks).",
    "speech": "How spoken dialogue is denoted (e.g. text wrapped in double quotes).",
    "internal_monologue": "How a character's unspoken thought is denoted.",
    "quotation": "How quoted or cited text inside speech or narration is denoted.",
}


def _array_tool(name: str, description: str, array_key: str, array_description: str, item_props: dict[str, str]) -> ToolSpec:
    """Build a standalone ToolSpec whose sole parameter is an array of fixed-shape
    string objects. The schema is static (the per-conversation variation lives in
    the array's runtime contents, not its shape), so it never busts a cache."""
    return ToolSpec(
        name=name,
        schema={
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        array_key: {
                            "type": "array",
                            "description": array_description,
                            "items": {
                                "type": "object",
                                "properties": {k: {"type": "string", "description": d} for k, d in item_props.items()},
                                "required": list(item_props),
                            },
                        }
                    },
                    "required": [array_key],
                },
            },
        },
        choice={"type": "function", "function": {"name": name}},
    )


ANALYZE_TOOL = _array_tool(
    TOOL_ANALYZE,
    "Record how each prose element is denoted in this conversation.",
    "records",
    "One record per element you can characterize from the prose; omit elements with no evidence.",
    {
        "category": "The element name, exactly as listed in the request.",
        "denotation": "A short description of how that element is marked in this conversation's prose.",
    },
)

REPORT_TOOL = _array_tool(
    TOOL_REPORT,
    "Report spans of the draft that violate the recorded prose format.",
    "violations",
    "One entry per offending span; report nothing for a clean draft.",
    {
        "excerpt": "The offending text, copied verbatim from the draft.",
        "category": "The single element name the span violates, exactly as listed.",
    },
)

PATCH_TOOL = _array_tool(
    TOOL_PATCH,
    "Apply minimal search/replace edits that bring flagged spans into the recorded format.",
    "patches",
    "One patch per flagged span.",
    {
        "search": "The exact text to replace, copied verbatim from the draft.",
        "replace": "That same text rewritten to the recorded format, wording unchanged.",
    },
)

# Every key the hooks read with ``cfg.get(...)`` is present here. The framework
# returns a non-empty config slot verbatim (no per-key merge with defaults), so a
# slot must never be written partially; the frontend always sends all keys, and
# this full default set covers the empty-slot path.
_CONFIG_DEFAULTS = {"max_iterations": 1, "prompt_mode": "minimal", "auto_analyze": False, "reasoning": False}

_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "max_iterations": {"type": "integer", "minimum": 0, "default": 1},
        "prompt_mode": {"type": "string", "enum": ["minimal", "extend"], "default": "minimal"},
        "auto_analyze": {"type": "boolean", "default": False},
        "reasoning": {"type": "boolean", "default": False},
    },
}

prose_format_llm_workflow = Workflow(
    id=WORKFLOW_ID,
    display_name="Prose Format (LLM)",
    tools=[ANALYZE_TOOL, REPORT_TOOL, PATCH_TOOL],
    config_defaults=_CONFIG_DEFAULTS,
    config_schema=_CONFIG_SCHEMA,
)
