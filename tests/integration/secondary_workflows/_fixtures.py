"""Test helpers for workflow hook coverage.

``make_workflow`` is a parametric ``Workflow`` builder with sensible
defaults; tests fill in only the hooks they care about. ``register_for_test``
is an async context manager that registers the workflow on enter and
surgically removes it from the global registry on exit, restoring
``TOOLS`` and ``STANDALONE_TOOLS`` to their pre-register snapshot. Tests
should always use the context manager so a failing assertion does not
leak state into neighbouring tests.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from backend.secondary_workflows import (
    ToolSpec,
    Workflow,
    register_workflow,
)
from backend.secondary_workflows import registry as _registry
from backend.tool_defs import STANDALONE_TOOLS, TOOLS


def make_workflow(
    workflow_id: str,
    *,
    display_name: str | None = None,
    priority: int = 0,
    pre_pipeline=None,
    post_pipeline=None,
    on_demand=None,
    regenerate=None,
    tools: list[ToolSpec] | None = None,
    config_defaults: dict | None = None,
    config_schema: dict | None = None,
    auto_regen_button: bool = True,
) -> Workflow:
    """Construct a ``Workflow`` with test-friendly defaults."""
    return Workflow(
        id=workflow_id,
        display_name=display_name or f"Test workflow {workflow_id}",
        priority=priority,
        pre_pipeline=pre_pipeline,
        post_pipeline=post_pipeline,
        on_demand=on_demand,
        regenerate=regenerate,
        tools=tools or [],
        config_defaults=config_defaults or {},
        config_schema=config_schema,
        auto_regen_button=auto_regen_button,
    )


@contextmanager
def register_for_test(workflow: Workflow) -> Iterator[Workflow]:
    """Register *workflow* for the duration of a ``with`` block.

    On enter: calls ``register_workflow``. On exit: restores the registry,
    ``TOOLS``, and ``STANDALONE_TOOLS`` to the snapshot captured before
    enter -- so a failing assertion does not leak workflow state into
    neighbouring tests.
    """
    workflows_snapshot = list(_registry._WORKFLOWS)
    by_id_snapshot = dict(_registry._WORKFLOWS_BY_ID)
    tools_snapshot = {n: dict(spec) for n, spec in TOOLS.items()}
    standalone_snapshot = set(STANDALONE_TOOLS)

    register_workflow(workflow)
    try:
        yield workflow
    finally:
        _registry._WORKFLOWS[:] = workflows_snapshot
        _registry._WORKFLOWS_BY_ID.clear()
        _registry._WORKFLOWS_BY_ID.update(by_id_snapshot)
        TOOLS.clear()
        TOOLS.update(tools_snapshot)
        STANDALONE_TOOLS.clear()
        STANDALONE_TOOLS.update(standalone_snapshot)
