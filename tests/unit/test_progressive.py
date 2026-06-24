"""Unit tests for the director-local progressive-fragment helpers."""

from __future__ import annotations

from backend.pipeline.passes.director import progressive

# ── select ───────────────────────────────────────────────────────────────────


class TestSelect:
    def _frags(self):
        return [
            {"id": "tension", "field_type": "progressive"},
            {"id": "plot_summary", "field_type": "string"},
            {"id": "threads", "field_type": "array"},
        ]

    def test_keeps_only_progressive_keys(self):
        values = {"tension": "uneasy", "plot_summary": "They fought.", "threads": ["a"]}
        assert progressive.select(values, self._frags()) == {"tension": "uneasy"}

    def test_drops_stale_keys_without_a_fragment(self):
        # A key that no longer maps to any progressive fragment is dropped.
        values = {"tension": "calm", "removed_field": "x"}
        assert progressive.select(values, self._frags()) == {"tension": "calm"}

    def test_symmetric_on_seed_and_extra_fields_shapes(self):
        # The same filter applies whether the input is prior seed state
        # (director["progressive_fields"]) or this turn's extra_fields.
        frags = self._frags()
        seed = {"tension": "calm"}
        extra = {"tension": "breaking point", "plot_summary": "x"}
        assert progressive.select(seed, frags) == {"tension": "calm"}
        assert progressive.select(extra, frags) == {"tension": "breaking point"}

    def test_empty_inputs(self):
        assert progressive.select({}, self._frags()) == {}
        assert progressive.select({"tension": "calm"}, []) == {}


# ── branch_baseline ──────────────────────────────────────────────────────────


class TestBranchBaseline:
    def test_no_grandparent_returns_empty(self):
        assert progressive.branch_baseline([]) == {}
        assert progressive.branch_baseline([{"role": "user", "content": "hi"}]) == {}

    def test_picks_last_assistant_message(self):
        history = [
            {"role": "assistant", "progressive_fields": {"tension": "calm"}},
            {"role": "user", "content": "go on"},
            {"role": "assistant", "progressive_fields": {"tension": "uneasy"}},
            {"role": "user", "content": "and then"},
        ]
        assert progressive.branch_baseline(history) == {"tension": "uneasy"}

    def test_assistant_without_progressive_fields_returns_empty(self):
        history = [{"role": "assistant", "content": "hi"}]
        assert progressive.branch_baseline(history) == {}

    def test_null_progressive_fields_returns_empty(self):
        history = [{"role": "assistant", "progressive_fields": None}]
        assert progressive.branch_baseline(history) == {}
