"""
predicates.py — Dependency-free turn predicates.

Three pure functions that answer "what mode is this turn in?":
``agent_enabled``, ``is_dual_model``, and ``resolve_persona_id``. They read
settings/conversation mappings and return a flag or id.

Sits below ``config`` (which imports the pass modules) so any module in the
package can call these without pulling in the heavier pass dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ..inference import LLMClient


def is_dual_model(agent_client: "LLMClient | None") -> bool:
    """Return True when the agent runs on a separate endpoint (dual-model mode).

    Single-model: writer and agent share one endpoint and KV cache.
    Dual-model: director + editor run on their own endpoint with a separate KV cache.
    """
    return agent_client is not None


def agent_enabled(settings: Mapping[str, Any]) -> bool:
    """Return True when the global Agent toggle is on (default on).

    All agent-gated features (director, editor, length guard, feedback, mood
    persistence) call this function, so the default-on behavior stays consistent.
    """
    return bool(settings.get("enable_agent", 1))


def resolve_persona_id(
    conv: Mapping[str, Any],
    card: Mapping[str, Any] | None,
    settings: Mapping[str, Any],
) -> int | None:
    """Return the effective persona id for a turn.

    Priority: conversation pin → character-card pin → global active persona.
    """
    return conv.get("persona_lock_id") or (card.get("persona_lock_id") if card else None) or settings.get("active_persona_id")
