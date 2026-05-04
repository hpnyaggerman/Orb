"""
kv_tracker.py — Lightweight KV-cache hit/miss estimator shared across passes.

Serializes the full prompt (messages + tools) for each LLM call, then computes
the actual character-level common prefix between consecutive calls to estimate
cache reuse.  Character counts are a proxy for token counts — no tokeniser needed.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def _serialize_prompt(messages: list[dict], tools: list[dict] | None) -> str:
    """Compact JSON serialization of the full prompt for prefix comparison."""
    parts = [json.dumps(m, separators=(",", ":")) for m in messages]
    if tools:
        parts.append(json.dumps(tools, separators=(",", ":")))
    return "\n".join(parts)


def _common_prefix_len(a: str, b: str) -> int:
    """Length of the longest common prefix between two strings."""
    i = 0
    limit = min(len(a), len(b))
    while i < limit and a[i] == b[i]:
        i += 1
    return i


class _KVCacheTracker:
    def __init__(self):
        self._entries: list[dict] = []

    def record(
        self, label: str, messages: list[dict], tools: list[dict] | None
    ) -> None:
        """Snapshot a single LLM call. Call once per pass (or per tool in the director)."""
        serialized = _serialize_prompt(messages, tools)
        self._entries.append(
            {
                "label": label,
                "serialized": serialized,
                "total_chars": len(serialized),
                "tools_names": (
                    [t.get("function", {}).get("name", "") for t in tools]
                    if tools
                    else []
                ),
            }
        )

    def log_summary(self) -> None:
        if not self._entries:
            return

        lines = ["KV cache comparison  (serialized prompt overlap):"]
        total_saved = 0

        for i, e in enumerate(self._entries):
            if i == 0:
                overlap = 0
                cache_note = "baseline"
            else:
                prev_serialized = self._entries[i - 1]["serialized"]
                overlap = _common_prefix_len(prev_serialized, e["serialized"])
                if overlap > 0:
                    total_saved += overlap
                    pct = overlap / len(prev_serialized) * 100 if prev_serialized else 0
                    prev_label = self._entries[i - 1]["label"]
                    cache_note = (
                        f"HIT  overlap={overlap} ({pct:.1f}%)  vs [{i-1}] {prev_label}"
                    )
                else:
                    cache_note = "BUST  no_overlap"

            tail = e["total_chars"] - overlap

            lines.append(
                f"  {e['label']:<28}  total={e['total_chars']:7d}  "
                f"tail={tail:6d}  {cache_note}"
            )

        lines.append(f"  Total estimated KV cache char savings: {total_saved}")
        logger.info("\n".join(lines))
