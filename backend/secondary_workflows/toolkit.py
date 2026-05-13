"""Stable import surface for workflow authors.

Workflows import from this module rather than reaching directly into
``backend.llm_client``, ``backend.prompt_builder``, etc. The set of
re-exports is the workflow author's API: LLM client, tool-schema
assembly, prompt assembly, macro resolution, read-only DB helpers for
core state, workflow-scoped storage wrappers, the forced-call helper,
the tool-overlay helper, and the editor audit helpers (for workflows
scoring their own outputs against the same audit logic the editor
runs).

Workflows do not import orchestration symbols, the transactional DB
helpers (``add_message``, ``create_swipe``, etc.), director-state
mutators, or pass internals. ``add_workflow_attachment`` is included as
the only attachment writer, scoped by the ``source = "workflow:..."``
guard so it cannot impersonate user uploads.
"""

from __future__ import annotations

from backend.database import (
    add_workflow_attachment,
    get_character_card,
    get_conversation,
    get_director_fragments,
    get_director_state,
    get_message_by_id,
    get_messages,
    get_mood_fragments,
    get_phrase_bank,
    get_user_personas,
)
from backend.llm_client import LLMClient, parse_tool_calls, reasoning_cfg
from backend.macros import Macros
from backend.passes.editor.audit import format_report, run_audit
from backend.prompt_builder import (
    build_prefix,
    compute_lorebook_injection_block,
    compute_style_injection_block,
    format_message_with_attachments,
)
from backend.tool_defs import STANDALONE_TOOLS, TOOLS, enabled_schemas

from ._forced_call import forced_tool_call
from .registry import (
    get_workflow_config,
    get_workflow_message_state,
    get_workflow_state,
    overlay_enable_tools,
    set_workflow_config,
    set_workflow_message_state,
    set_workflow_state,
)


__all__ = [
    "LLMClient",
    "Macros",
    "STANDALONE_TOOLS",
    "TOOLS",
    "add_workflow_attachment",
    "build_prefix",
    "compute_lorebook_injection_block",
    "compute_style_injection_block",
    "enabled_schemas",
    "forced_tool_call",
    "format_message_with_attachments",
    "format_report",
    "get_character_card",
    "get_conversation",
    "get_director_fragments",
    "get_director_state",
    "get_message_by_id",
    "get_messages",
    "get_mood_fragments",
    "get_phrase_bank",
    "get_user_personas",
    "get_workflow_config",
    "get_workflow_message_state",
    "get_workflow_state",
    "overlay_enable_tools",
    "parse_tool_calls",
    "reasoning_cfg",
    "run_audit",
    "set_workflow_config",
    "set_workflow_message_state",
    "set_workflow_state",
]
