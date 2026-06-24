"""
passes/director/prompt_rewrite.py — The user-prompt-rewrite feature.

Rewrites a vague user message into a fuller prompt before the writer runs, via
the ``rewrite_user_prompt`` tool. The director runs it first (see
:func:`order_director_tools`) so a user can stop before the full director runs
if they don't like the result; its reasoning is suppressed because the rephrase
is mechanical and adds latency.

The tool schema stays in ``tool_registry.py`` (part of the cached tool blob;
moving it would bust the KV cache). The instruction template lives in
``prompt_builder.py``. Only the Python glue lives here — matching the pattern in
``length_guard.py``.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: The tool name, as a single source of truth for the literal that the schema in
#: ``tool_registry.py`` registers and that the director/orchestrator key off.
REWRITE_TOOL_NAME = "rewrite_user_prompt"


def extract_rewritten_message(args: Mapping[str, Any]) -> str | None:
    """Pull the rewritten message from a ``rewrite_user_prompt`` tool call.

    Returns ``None`` when the argument is absent or empty (treated as no rewrite).
    """
    return args.get("refined_message") or None


def order_director_tools(tool_names: Iterable[str]) -> list[str]:
    """Sort director tools so ``rewrite_user_prompt`` runs first.

    Rewrite-first lets users abort early before the full director (mood/scene
    direction) runs. ``direct_scene`` follows; other tools sort after both.
    """
    priority = [REWRITE_TOOL_NAME, "direct_scene"]
    return sorted(tool_names, key=lambda x: priority.index(x) if x in priority else len(priority))


def suppresses_reasoning(name: str) -> bool:
    """Return True if tool *name* should run without reasoning.

    ``rewrite_user_prompt`` does — it is a mechanical rephrase and suppressing
    its reasoning reduces the pre-writer latency the user waits through.
    """
    return name == REWRITE_TOOL_NAME


def apply_rewrite(user_message: str, rewritten_msg: str | None) -> tuple[str, bool]:
    """Return the writer's effective message and whether a rewrite occurred.

    Returns ``(effective_msg, did_rewrite)``. The orchestrator uses the flag to
    gate the ``prompt_rewritten`` SSE event and the DB overwrite; this function
    is pure (no I/O).
    """
    return (rewritten_msg or user_message, bool(rewritten_msg))


def disable_rewrite(enabled_tools: Mapping[str, bool]) -> dict[str, bool]:
    """Return *enabled_tools* with ``rewrite_user_prompt`` forced off.

    Used by the steered-regenerate paths, whose OOC steering message must not be
    rewritten by the director. Returns a fresh dict rather than mutating the input.
    """
    return {**enabled_tools, REWRITE_TOOL_NAME: False}
