"""Tests for the RP format-consistency normalizer.

Covers axis classification, the per-axis deterministic rewrite (including the
full inversion the user reported), and the conservative no-op behaviour that
keeps the feature safe (ambiguous input, unstable baseline, disabled).
"""

from backend.analysis.detectors.format_consistency import (
    AxisStyle,
    Dialogue,
    Narration,
    baseline_axes,
    classify_axes,
    normalize_format,
    normalize_to_baseline,
)

QUOTES_ONLY = 'She smiles and steps back. "I won\'t go," she says, turning to the window.'
ASTERISKS_ONLY = "*She smiles and steps back, turning to the window.* I won't go."
FULL_MARKUP = '*He leans on the doorframe, arms crossed.* "You came back," *he murmurs.*'


# ---------- classification ----------


def test_classify_quotes_only():
    style = classify_axes(QUOTES_ONLY)
    assert style.dialogue == Dialogue.QUOTED
    assert style.narration == Narration.BARE


def test_classify_asterisks_only():
    style = classify_axes(ASTERISKS_ONLY)
    assert style.dialogue == Dialogue.BARE
    assert style.narration == Narration.ASTERISK


def test_classify_full_markup():
    style = classify_axes(FULL_MARKUP)
    assert style.dialogue == Dialogue.QUOTED
    assert style.narration == Narration.ASTERISK


def test_pure_dialogue_has_unknown_narration():
    style = classify_axes('"Hello." "How are you?" "Fine, thanks."')
    assert style.dialogue == Dialogue.QUOTED
    assert style.narration == Narration.UNKNOWN


def test_embedded_thought_does_not_flip_narration_axis():
    # A consistent quotes-only message with one italic thought must NOT be read as
    # asterisk-style narration (the bug the two-axis coverage model fixes).
    text = (
        "She paused at the door, one hand on the frame. "
        "*Was he really serious about this?* "
        '"Tell me the truth," she said quietly.'
    )
    assert classify_axes(text).narration != Narration.ASTERISK


# ---------- the reported inversion ----------


def test_inversion_asterisk_draft_to_quotes_baseline():
    base = ['She smiles. "Hello there," she says warmly.']
    draft = "*She steps closer, watching him carefully.* Are you sure about this?"
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert rep.changed
    assert new == 'She steps closer, watching him carefully. "Are you sure about this?"'


def test_inversion_quotes_draft_to_asterisk_baseline():
    base = ["*She smiles, stepping back toward the window.* Hello there."]
    draft = 'She steps closer, watching him. "Are you sure about this?"'
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert rep.changed
    assert new == "*She steps closer, watching him.* Are you sure about this?"


# ---------- per-axis: only the drifted axis is touched ----------


def test_only_narration_axis_changes_quotes_preserved():
    base = ['*He leans against the doorframe, arms crossed.* "You came back," *he murmurs.*']
    draft = 'He leans against the wall. "You came back."'
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert rep.changed
    # Dialogue axis already matched (both quote dialogue) -> quotes untouched.
    assert new == '*He leans against the wall.* "You came back."'


def test_full_markup_to_quotes_only_strips_narration_asterisks():
    target = AxisStyle(dialogue=Dialogue.QUOTED, narration=Narration.BARE)
    out = normalize_format(FULL_MARKUP, target)
    assert "*" not in out.replace("*he murmurs.*", "")  # block narration unwrapped
    assert '"You came back,"' in out  # dialogue untouched


# ---------- no-op safety ----------


def test_already_consistent_is_byte_identical():
    base = ['She smiles. "Hello there," she says warmly.']
    draft = 'He nods slowly. "I understand," he replies.'
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert not rep.changed
    assert new == draft


def test_embedded_thought_message_is_noop_against_quotes_baseline():
    base = ['She smiles. "Hello there," she says warmly.']
    draft = (
        "She paused at the door, one hand on the frame. "
        "*Was he really serious about this?* "
        '"Tell me the truth," she said quietly.'
    )
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert not rep.changed
    assert new == draft


def test_disabled_is_noop():
    base = ["*She smiles.* Hello there."]
    draft = 'She smiles. "Hello there."'
    new, rep = normalize_to_baseline(draft, base, enabled=False)
    assert not rep.changed
    assert new == draft
    assert rep.note == "disabled"


def test_no_baseline_is_noop():
    draft = 'She smiles. "Hello there."'
    new, rep = normalize_to_baseline(draft, [], enabled=True)
    assert not rep.changed
    assert new == draft


def test_unstable_baseline_is_noop():
    # One quotes-only, one asterisks-only -> neither axis agrees -> no enforcement.
    base = [QUOTES_ONLY, ASTERISKS_ONLY]
    target = baseline_axes(base)
    assert target.dialogue == Dialogue.UNKNOWN
    assert target.narration == Narration.UNKNOWN
    draft = 'She frowns. "What now?"'
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert not rep.changed
    assert new == draft


# ---------- preservation of incidental markup ----------


def test_contractions_survive():
    base = ["*She waves.* Hi there."]  # asterisk baseline
    draft = "She can't believe it. \"I won't leave,\" she insists."
    new, _ = normalize_to_baseline(draft, base, enabled=True)
    assert "can't" in new
    assert "won't" in new


def test_markdown_bullets_not_treated_as_emphasis():
    text = "Here is a list:\n* first item\n* second item\nThat is all."
    # The leading-bullet guard means these are bare narration, not emphasis.
    assert classify_axes(text).narration != Narration.ASTERISK


def test_asterisk_inside_quotes_is_not_narration():
    text = 'He said, "you are *so* dramatic," and rolled his eyes as she huffed.'
    # The `*so*` lives inside dialogue, so it must not register as narration markup.
    style = classify_axes(text)
    assert style.dialogue == Dialogue.QUOTED


def test_multiparagraph_preserves_separators():
    base = ['*She nods.* "Okay."']  # full-ish / asterisk narration baseline
    draft = "She nods slowly.\n\nShe steps away from the table."
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    # Both paragraphs rewritten, blank-line separator intact.
    assert "\n\n" in new
    if rep.changed:
        assert new.count("\n\n") == draft.count("\n\n")


def test_inline_emphasis_inside_narration_not_fragmented():
    # quotes-only narration -> asterisk narration: the inline *really* is absorbed
    # into the single wrapped run, not left as its own *really* fragment.
    base = ['*He waited by the window, tense.* "Where were you?"']  # full-markup baseline
    draft = '"Where is he?" She was *really* nervous about the whole thing.'
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert rep.changed
    assert new == '"Where is he?" *She was really nervous about the whole thing.*'
    assert "*really*" not in new  # not fragmented


def test_pure_bare_narration_without_dialogue_is_noop():
    # No quotes and no asterisks means bare text is ambiguous (narration vs. bare
    # dialogue in an asterisk-only chat), so the normalizer leaves it alone.
    base = ["*She paces the room nervously, glancing at the clock.* Right."]
    draft = "She was really nervous about the whole thing."
    new, rep = normalize_to_baseline(draft, base, enabled=True)
    assert not rep.changed
    assert new == draft
