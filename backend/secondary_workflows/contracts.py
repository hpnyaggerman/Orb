"""Boundary contracts for the workflow subsystem.

Defines the four context dataclasses passed to workflow hooks, the
``ToolSpec`` declaration carried on a ``Workflow``, and the ``_readonly``
recursive wrapper that turns mutable orchestrator-derived structures into
deeply read-only views.

Mutation behavior: every Ctx is ``frozen=True`` (field reassignment raises
``FrozenInstanceError``) and mutable fields are expected to be passed in
already wrapped via ``_readonly(...)``. Any write into a wrapped container
at any nesting depth raises immediately: ``TypeError`` from
``MappingProxyType`` item assignment, ``AttributeError`` from ``tuple.append``
and ``frozenset.add``, ``TypeError`` from tuple item assignment.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


def _readonly(obj: Any) -> Any:
    """Return a recursive read-only view of *obj*.

    - dict -> MappingProxyType (keys/values recursed)
    - list / tuple -> tuple (values recursed)
    - set / frozenset -> frozenset (values recursed)
    - bytearray -> bytes
    - everything else returned as-is

    Strings, bytes, ints, floats, None, and other immutable primitives pass
    through unchanged. MappingProxyType passes through as-is (it isn't a
    ``dict`` subclass, so the dict branch does not match), which keeps the
    helper idempotent on already-wrapped values.
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _readonly(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_readonly(v) for v in obj)
    if isinstance(obj, (set, frozenset)):
        return frozenset(_readonly(v) for v in obj)
    if isinstance(obj, bytearray):
        return bytes(obj)
    return obj


@dataclass
class ToolSpec:
    """A tool a workflow contributes to the global tool registry.

    ``name`` must equal ``schema["function"]["name"]``. ``choice`` is the
    pre-built ``tool_choice`` payload (almost always
    ``{"type": "function", "function": {"name": name}}``) so forced-call
    sites can pass it directly to ``client.complete(tool_choice=...)``.
    ``standalone`` defaults to True: workflow tools stay out of the pipeline
    union and are only reachable via direct forced calls. Setting False
    merges the tool into ``enabled_schemas(...)``'s output (subject to the
    workflow's ``enable_tools`` yields gating it per turn).
    """

    name: str
    schema: dict
    choice: dict
    standalone: bool = True


@dataclass(frozen=True)
class PreCtx:
    """Inputs available to a workflow's pre-pipeline hook.

    Wrapped fields (``history``, ``settings``, ``prefix``,
    ``enabled_tools_pre_merge``) are recursively read-only at the point the
    orchestrator constructs this Ctx; mutation attempts at any nesting
    depth raise immediately. ``turn_scratch``, ``client``, and
    ``kv_tracker`` are intentionally not wrapped -- they are the documented
    mutation channel, the per-turn LLM client, and the per-turn cache
    aggregator respectively, ref-shared across every PreCtx and PostCtx in
    the same turn.

    ``prefix`` carries the pipeline prefix *before* extra system blocks
    contributed by pre-pipeline ``system_prompt`` yields have been
    appended; ``enabled_tools_pre_merge`` carries the pre-merge enable map
    (``settings["enabled_tools"]``, zeroed wholesale when ``agent_on`` is
    false). Pre-pipeline forced calls that want pipeline tools-bytes cache
    reuse pass these through to ``forced_tool_call``.
    """

    conversation_id: str
    history: tuple
    last_user_message: str
    settings: MappingProxyType
    prefix: tuple
    enabled_tools_pre_merge: MappingProxyType
    turn_scratch: dict
    client: Any
    kv_tracker: Any


@dataclass(frozen=True)
class PostCtx:
    """Inputs available to a workflow's post-pipeline hook.

    Constructed fresh per workflow during post-pipeline iteration with the
    current draft (any prior hook's ``draft_replaced`` is already applied).
    ``prefix`` carries the final pipeline prefix -- extras from pre-pipeline
    ``system_prompt`` yields have already been appended -- matching the
    bytes director / writer / editor saw. ``enabled_tools`` is the merged
    pipeline tool-enable map. Post-pipeline forced calls that want full KV
    cache reuse with the pipeline pass both ``prefix`` and
    ``enabled_tools`` through to ``forced_tool_call``.
    """

    conversation_id: str
    draft: str
    effective_msg: str
    director_output: MappingProxyType
    settings: MappingProxyType
    prefix: tuple
    enabled_tools: MappingProxyType
    turn_scratch: dict
    client: Any
    kv_tracker: Any


@dataclass(frozen=True)
class OnDemandCtx:
    """Inputs available to a workflow's on-demand HTTP handler.

    No ``turn_scratch`` or ``kv_tracker``: on-demand handlers run outside
    any turn, Python locals serve in place of scratch, and on-demand LLM
    calls do not participate in turn cache accounting.
    """

    conversation_id: str
    history: tuple
    last_user_message: str
    settings: MappingProxyType
    client: Any


@dataclass(frozen=True)
class RegenCtx:
    """Inputs available to a workflow's regenerate HTTP handler.

    ``original_attachment`` carries the row currently being regenerated
    (the workflow may read its own prior workflow-specific metadata keys
    off it as a starting point). ``history`` reflects the current
    conversation at regen time, not the conversation as it stood at the
    moment of original creation. No ``turn_scratch`` or ``kv_tracker``:
    regen runs outside any turn.
    """

    conversation_id: str
    message_id: int
    attachment_id: int
    original_attachment: MappingProxyType
    history: tuple
    last_user_message: str
    settings: MappingProxyType
    client: Any
