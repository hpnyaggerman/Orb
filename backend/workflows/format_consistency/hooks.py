"""Post-pipeline hook binding the format-consistency normalizer to the turn.

Orchestration only: read the global config gate, reconstruct the recent
assistant-message baseline from the turn's history, and call the pure
``normalize_to_baseline`` from the analysis layer. On an actual rewrite, yield
one ``draft_replaced`` event -- the bridge validates it and emits the
``writer_rewrite`` SSE itself (the same payload the old editor-pass stage sent).
"""

from __future__ import annotations

import logging

from ..contracts import EV_DRAFT_REPLACED
from ..toolkit import get_workflow_config, normalize_to_baseline

logger = logging.getLogger(__name__)

WORKFLOW_ID = "format_consistency"
BASELINE_WINDOW = 3


def _baseline_window(history) -> list[str]:
    """The recent assistant-message window (newest first, up to 3) whose markup
    convention the draft is held to.

    Mirrors the fallback window the editor pass derived from its cached prefix:
    assistant history is always plain text, so a non-str body (the multimodal
    list form rides only user messages) has nothing to contribute.
    """
    window: list[str] = []
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                window.append(content)
                if len(window) >= BASELINE_WINDOW:
                    break
    return window


async def post_pipeline(ctx):
    """Hold the finished draft's markup convention to the recent messages'.

    Gated solely on the global config slot's ``enabled`` flag (default True, so
    a fresh DB preserves the prior always-on behaviour). ``normalize_to_baseline``
    is a conservative no-op -- it rewrites only when the baseline window agrees
    on a convention and the draft drifts from it -- so when nothing changes the
    hook yields nothing (no malformed-event warning).
    """
    cfg = await get_workflow_config(WORKFLOW_ID)
    if not cfg.get("enabled", True):
        return
    baseline_msgs = _baseline_window(ctx.history)
    # enabled=True is constant here: the real on/off gate is the config check
    # above. The function's enabled param is vestigial on this path but kept for
    # the tested pure API.
    new_text, drift = normalize_to_baseline(ctx.draft, baseline_msgs, enabled=True)
    if drift.changed:
        logger.info("format-consistency: normalized draft (%s)", drift.transition())
        yield {"type": EV_DRAFT_REPLACED, "draft": new_text}
