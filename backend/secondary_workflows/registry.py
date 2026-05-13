"""Workflow registry, registration entry point, and per-workflow storage.

The registry is a process-local list of ``Workflow`` objects ordered by
``(priority, id)`` so iteration is independent of import order. Workflows
register at import time via ``register_workflow``; the orchestrator and
manifest endpoint read ``list_workflows()`` at runtime.

Storage wrappers (``get_workflow_state`` etc.) are thin awaiting wrappers
over ``backend.database`` so the toolkit has a single namespace for both
core reads and workflow-scoped reads. ``get_workflow_config`` is the one
exception that adds behavior: it falls back to the workflow's
``config_defaults`` when the DB slot is empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Mapping, Optional

from backend.database import (
    get_workflow_config as _db_get_workflow_config,
    get_workflow_message_state as _db_get_workflow_message_state,
    get_workflow_state as _db_get_workflow_state,
    set_workflow_config as _db_set_workflow_config,
    set_workflow_message_state as _db_set_workflow_message_state,
    set_workflow_state as _db_set_workflow_state,
)
from backend.tool_defs import (
    BUILTIN_TOOL_NAMES,
    STANDALONE_TOOLS,
    TOOLS,
    register_tool,
)

from .contracts import OnDemandCtx, PostCtx, PreCtx, RegenCtx, ToolSpec


PreHook = Callable[[PreCtx], AsyncIterator[dict]]
PostHook = Callable[[PostCtx], AsyncIterator[dict]]
OnDemandHook = Callable[[OnDemandCtx, dict], Awaitable[dict]]
RegenHook = Callable[[RegenCtx, dict], Awaitable[list[dict]]]


@dataclass
class Workflow:
    """The entire registration surface for a workflow.

    Hooks default to ``None``; any combination may be set. ``priority``
    breaks ties by ``id`` alphabetical (default 0 leaves room on both
    sides for run-before-everyone and run-after-everyone). ``tools``
    schemas land in the global registry via ``register_workflow`` -- the
    workflow does not call ``register_tool`` directly. ``config_defaults``
    is the dict returned by ``get_workflow_config`` when the persisted
    slot is empty.
    """

    id: str
    display_name: str
    priority: int = 0
    pre_pipeline: Optional[PreHook] = None
    post_pipeline: Optional[PostHook] = None
    on_demand: Optional[OnDemandHook] = None
    regenerate: Optional[RegenHook] = None
    tools: list[ToolSpec] = field(default_factory=list)
    config_defaults: dict = field(default_factory=dict)
    config_schema: Optional[dict] = None
    auto_regen_button: bool = True


class ToolNameCollision(Exception):
    """Raised when a workflow tries to claim a tool name that is already
    taken by a built-in pass or by another registered workflow."""


_WORKFLOWS: list[Workflow] = []
_WORKFLOWS_BY_ID: dict[str, Workflow] = {}


def register_workflow(w: Workflow) -> None:
    """Register or replace a workflow. Idempotent on ``w.id``.

    Tool diff against any prior registration of the same id:
      - names in new only -> ``register_tool`` is called fresh
      - names in both -> ``register_tool`` overwrites schema/choice and
        toggles the standalone bit symmetrically
      - names in old only -> removed from ``TOOLS`` and
        ``STANDALONE_TOOLS`` so the workflow's declaration stays the
        single source of truth for what it owns

    Validation order: built-in name reservation first (more informative
    error wins over a cross-workflow collision on the same name), then
    cross-workflow collision on names this registration is newly claiming.
    Both raise ``ToolNameCollision`` before any state mutation, so a
    rejected call leaves the registry, ``TOOLS``, and ``STANDALONE_TOOLS``
    exactly as they were. The list is re-sorted on every insert/replace so
    iteration order is determined by ``(priority, id)`` alone, not by
    import order.
    """
    for spec in w.tools:
        if spec.name in BUILTIN_TOOL_NAMES:
            raise ToolNameCollision(f"workflow {w.id!r} cannot claim built-in tool name {spec.name!r}")

    old = _WORKFLOWS_BY_ID.get(w.id)
    old_tool_names = {t.name for t in old.tools} if old else frozenset()
    new_tool_names = {t.name for t in w.tools}

    newly_claimed = new_tool_names - old_tool_names
    for name in newly_claimed:
        for other in _WORKFLOWS:
            if other.id == w.id:
                continue
            if any(t.name == name for t in other.tools):
                raise ToolNameCollision(f"workflow {w.id!r} cannot claim tool name {name!r} " f"owned by workflow {other.id!r}")

    for spec in w.tools:
        register_tool(spec.name, spec.schema, spec.choice, standalone=spec.standalone)

    for orphan in old_tool_names - new_tool_names:
        TOOLS.pop(orphan, None)
        STANDALONE_TOOLS.discard(orphan)

    _WORKFLOWS_BY_ID[w.id] = w
    if old is not None:
        for i, existing in enumerate(_WORKFLOWS):
            if existing.id == w.id:
                _WORKFLOWS[i] = w
                break
    else:
        _WORKFLOWS.append(w)
    _WORKFLOWS.sort(key=lambda x: (x.priority, x.id))


def list_workflows() -> list[Workflow]:
    """Return a shallow copy of the registry ordered by ``(priority, id)``."""
    return list(_WORKFLOWS)


def get_workflow(workflow_id: str) -> Optional[Workflow]:
    """Look up a workflow by id, or None if not registered."""
    return _WORKFLOWS_BY_ID.get(workflow_id)


async def get_workflow_state(conv_id: str, workflow_id: str) -> dict | None:
    """Return the workflow's per-conversation slot, or None if empty."""
    return await _db_get_workflow_state(conv_id, workflow_id)


async def set_workflow_state(conv_id: str, workflow_id: str, payload: dict | None) -> None:
    """Write the workflow's per-conversation slot. None removes it."""
    await _db_set_workflow_state(conv_id, workflow_id, payload)


async def get_workflow_message_state(message_id: int, workflow_id: str) -> dict | None:
    """Return the workflow's per-message slot, or None if empty."""
    return await _db_get_workflow_message_state(message_id, workflow_id)


async def set_workflow_message_state(message_id: int, workflow_id: str, payload: dict | None) -> None:
    """Write the workflow's per-message slot. None removes it."""
    await _db_set_workflow_message_state(message_id, workflow_id, payload)


async def get_workflow_config(workflow_id: str) -> dict:
    """Return the workflow's global config slot.

    Falls back to the workflow's ``config_defaults`` (fresh copy) when the
    persisted slot is empty so callers can read into a populated dict
    without an existence check. An unregistered ``workflow_id`` with an
    empty slot returns an empty dict.
    """
    raw = await _db_get_workflow_config(workflow_id)
    if raw:
        return raw
    w = _WORKFLOWS_BY_ID.get(workflow_id)
    if w is not None:
        return dict(w.config_defaults)
    return {}


async def set_workflow_config(workflow_id: str, payload: dict) -> None:
    """Write the workflow's global config slot. Empty dict clears it."""
    await _db_set_workflow_config(workflow_id, payload)


def overlay_enable_tools(
    base: Mapping[str, bool],
    contribution: set[str] | Mapping[str, bool] | None,
) -> dict[str, bool]:
    """Return a fresh mutable dict copy of *base* with *contribution*'s
    True entries merged in. Mirrors the orchestrator merge semantics:
    True wins, False is ignored. None or an empty contribution returns a
    fresh copy of *base* unchanged.

    Accepts any ``Mapping`` for *base* including a ``MappingProxyType``;
    the return is always a plain ``dict`` the caller may mutate freely
    (e.g. to pass to ``forced_tool_call``'s ``enabled_tools=`` argument).
    Contribution may be a ``set`` (presence = enable) or a ``Mapping``
    (True entries kept, False entries dropped). The orchestrator does the
    logged-warning at its own merge site; this helper trusts the caller.
    """
    result = dict(base)
    if contribution is None:
        return result
    if isinstance(contribution, (set, frozenset)):
        for name in contribution:
            result[name] = True
    else:
        for name, enabled in contribution.items():
            if enabled:
                result[name] = True
    return result
