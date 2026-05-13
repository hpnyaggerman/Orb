"""Workflow subsystem package.

Public surface re-exported from this module:
  - ``Workflow``, ``register_workflow``, ``list_workflows``,
    ``get_workflow``, ``ToolNameCollision``
  - ``ToolSpec``, ``PreCtx``, ``PostCtx``, ``OnDemandCtx``, ``RegenCtx``
  - per-workflow storage wrappers and ``overlay_enable_tools``

Workflow authors should import day-to-day helpers from
``backend.secondary_workflows.toolkit`` instead -- that module is the
stable import surface for LLM client, prompt assembly, DB readers, and
the forced-call helper. This module is the registration / typing
surface.

First-party workflow subpackages (e.g. ``backend/secondary_workflows/tts/``)
import themselves here when they land so ``import backend.secondary_workflows``
is sufficient to run every registration side effect.
"""

from __future__ import annotations

from .contracts import (
    OnDemandCtx,
    PostCtx,
    PreCtx,
    RegenCtx,
    ToolSpec,
    _readonly,
)
from .registry import (
    ToolNameCollision,
    Workflow,
    get_workflow,
    get_workflow_config,
    get_workflow_message_state,
    get_workflow_state,
    list_workflows,
    overlay_enable_tools,
    register_workflow,
    set_workflow_config,
    set_workflow_message_state,
    set_workflow_state,
)


__all__ = [
    "OnDemandCtx",
    "PostCtx",
    "PreCtx",
    "RegenCtx",
    "ToolNameCollision",
    "ToolSpec",
    "Workflow",
    "_readonly",
    "get_workflow",
    "get_workflow_config",
    "get_workflow_message_state",
    "get_workflow_state",
    "list_workflows",
    "overlay_enable_tools",
    "register_workflow",
    "set_workflow_config",
    "set_workflow_message_state",
    "set_workflow_state",
]
