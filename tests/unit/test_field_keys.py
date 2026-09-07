"""Fragment ids on the wire and on the way back: wire_field, fold_key, match_folded, folded_collisions."""

from __future__ import annotations

from backend.core import fold_key, folded_collisions, match_folded
from backend.inference import wire_field


def test_fold_key_ignores_case_and_separators():
    assert fold_key("user-intent-hypothesis") == "userintenthypothesis"
    assert fold_key("User_Intent_Hypothesis") == "userintenthypothesis"
    assert fold_key("userintenthypothesis") == "userintenthypothesis"
    assert fold_key("user-intents") != fold_key("user-intent")


def test_match_folded_prefers_exact_then_first_in_order():
    ids = ["plot_thread", "plot-thread", "pacing"]
    assert match_folded("plot-thread", ids) == "plot-thread"
    assert match_folded("PlotThread", ids) == "plot_thread"
    assert match_folded("pacing", ids) == "pacing"
    assert match_folded("tempo", ids) is None
    assert match_folded("pacing", []) is None


def test_folded_collisions_pairs_each_later_id_with_the_first():
    assert folded_collisions(["a-b", "c", "a_b", "AB", "d"]) == [("a-b", "a_b"), ("a-b", "AB")]
    assert folded_collisions(["a", "b"]) == []


def test_wire_field_lowercases_and_underscores():
    assert wire_field("user-intent-hypothesis") == "user_intent_hypothesis"
    assert wire_field("Plot-Thread") == "plot_thread"
    assert wire_field("next_event") == "next_event"
    assert match_folded(wire_field("user-intent-hypothesis"), ["user-intent-hypothesis"]) == "user-intent-hypothesis"
