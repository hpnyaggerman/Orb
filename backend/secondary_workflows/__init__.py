"""Workflow subsystem package.

Public surface re-exported from this module:
  - ``Workflow``, ``Subscription``, ``HookType``, ``ToolNameCollision``,
    ``WorkflowMandateError``
  - ``register_workflow``, ``subscribe``, ``iter_subscriptions``,
    ``get_subscription``, ``workflow_has_hook``, ``list_workflows``,
    ``get_workflow``, ``finalize_registry``
  - ``ToolSpec``, ``PreCtx``, ``PostCtx``, ``OnDemandCtx``, ``RegenCtx``,
    ``RerollGenCtx``
  - per-workflow storage wrappers and ``overlay_enable_tools``

Workflow authors should import day-to-day helpers from
``backend.secondary_workflows.toolkit`` instead -- that module is the
stable import surface for LLM client, prompt assembly, DB readers, and
the forced-call helper. This module is the registration / typing
surface.

First-party workflows live under ``backend/secondary_workflows/`` and
are wired in here above the ``finalize_registry()`` call at the bottom
of this file: each workflow's metadata is registered via
``register_workflow``, then each of its hooks is attached via
``subscribe`` with a per-hook priority. Import-time ordering of those
calls determines the registry's iteration order and the manifest order
surfaced to the frontend. The final ``finalize_registry()`` call
validates that every ``produces_artifacts=True`` workflow has both
``REGENERATE`` and ``REROLL_GEN`` subscriptions; a violation raises
``WorkflowMandateError`` at import time.
"""

from __future__ import annotations

from .contracts import (
    HookType,
    OnDemandCtx,
    PostCtx,
    PreCtx,
    RegenCtx,
    RerollGenCtx,
    ToolSpec,
    _readonly,
)
from .registry import (
    Subscription,
    ToolNameCollision,
    Workflow,
    WorkflowMandateError,
    finalize_registry,
    get_subscription,
    get_workflow,
    get_workflow_config,
    get_workflow_message_state,
    get_workflow_state,
    iter_subscriptions,
    list_workflows,
    overlay_enable_tools,
    register_workflow,
    set_workflow_config,
    set_workflow_message_state,
    set_workflow_state,
    subscribe,
    workflow_has_hook,
)


__all__ = [
    "HookType",
    "OnDemandCtx",
    "PostCtx",
    "PreCtx",
    "RegenCtx",
    "RerollGenCtx",
    "Subscription",
    "ToolNameCollision",
    "ToolSpec",
    "Workflow",
    "WorkflowMandateError",
    "_readonly",
    "finalize_registry",
    "get_subscription",
    "get_workflow",
    "get_workflow_config",
    "get_workflow_message_state",
    "get_workflow_state",
    "iter_subscriptions",
    "list_workflows",
    "overlay_enable_tools",
    "register_workflow",
    "set_workflow_config",
    "set_workflow_message_state",
    "set_workflow_state",
    "subscribe",
    "workflow_has_hook",
]


finalize_registry()
