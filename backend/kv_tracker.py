"""
kv_tracker.py — Lightweight KV-cache hit/miss estimator shared across passes.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


class _KVCacheTracker:
    """Accumulates per-call prompt character counts to estimate KV cache reuse across passes.

    Each LLM call records (label, messages, tools).  After all passes complete,
    ``log_summary`` prints a table showing total prompt size, tail size, tools
    size, and whether the shared prefix was a cache HIT or BUST vs the previous
    call.  Character counts are a proxy for token counts — no tokeniser needed.
    """

    def __init__(self, prefix_chars: int):
        self._prefix_chars = prefix_chars
        self._entries: list[dict] = []

    def record(
        self, label: str, messages: list[dict], tools: list[dict] | None
    ) -> None:
        """Snapshot a single LLM call. Call once per pass (or per tool in the director)."""
        msg_chars = sum(len(m.get("content") or "") for m in messages)
        tools_chars = len(json.dumps(tools, separators=(",", ":"))) if tools else 0
        self._entries.append(
            {
                "label": label,
                "msg_chars": msg_chars,
                "tail_chars": msg_chars - self._prefix_chars,
                "tools_chars": tools_chars,
                "tools_names": [t["function"]["name"] for t in tools] if tools else [],
            }
        )

    def log_summary(self) -> None:
        if not self._entries:
            return
        lines = [f"KV cache comparison  (shared prefix={self._prefix_chars} chars):"]
        prev_tools_names: list | None = None
        prev_tools_chars = 0
        total_saved = 0

        for i, e in enumerate(self._entries):
            total = e["msg_chars"] + e["tools_chars"]
            if i == 0:
                cache_note = "baseline"
                saved = 0
            elif e["tools_names"] == prev_tools_names:
                saved = self._prefix_chars + prev_tools_chars
                total_saved += saved
                cache_note = f"HIT  saved={saved}"
            else:
                saved = 0
                cache_note = (
                    f"BUST tools_changed {prev_tools_names!r} → {e['tools_names']!r}"
                )

            lines.append(
                f"  {e['label']:<28}  total={total:7d}  "
                f"tail={e['tail_chars']:6d}  tools={e['tools_chars']:6d}  {cache_note}"
            )
            prev_tools_names = e["tools_names"]
            prev_tools_chars = e["tools_chars"]

        lines.append(f"  Total estimated KV cache char savings: {total_saved}")
        logger.info("\n".join(lines))
