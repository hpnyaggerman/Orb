"""
Tests for anti-echo detection — flagging the assistant parroting the user's last
message back as a question.

Organised into:
  - TRUE POSITIVES  – echoes we *want* to catch
  - FALSE POSITIVES – legitimate questions/statements that must *not* trigger
  - EDGE CASES      – boundary inputs
"""

from __future__ import annotations

from backend.analysis.detectors.anti_echo import detect_anti_echo

# ═══════════════════════════════════════════════════════════════════════════════
# TRUE POSITIVES
# ═══════════════════════════════════════════════════════════════════════════════


class TestTruePositives:
    def test_quoted_echo_with_repeat_verb(self):
        """The canonical case: a quoted question copying the user's dialogue."""
        result = detect_anti_echo('"Absolutely no money?" She repeats.', '"I have absolutely no money."')
        assert len(result.flagged_echoes) == 1
        flagged = result.flagged_echoes[0]
        assert "absolutely no money" in flagged.matched_phrase
        assert flagged.n_words == 3

    def test_quoted_echo_with_narration_leadin(self):
        """The quote is extracted from its narration lead-in, so only the
        question ("Ice cream?") is flagged — not "He blinks" or the rest."""
        result = detect_anti_echo('He blinks, "Ice cream? You\'re a grown man."', '"I got some ice cream."')
        assert len(result.flagged_echoes) == 1
        assert result.flagged_echoes[0].echo == "Ice cream?"
        assert result.flagged_echoes[0].matched_phrase == "ice cream"

    def test_unquoted_assistant_question_still_caught(self):
        """The *assistant's* echo need not be quoted — an unquoted narration
        question that copies the user's dialogue is still flagged."""
        result = detect_anti_echo("Ice cream? He blinks.", '"I got some ice cream."')
        assert len(result.flagged_echoes) == 1
        assert result.flagged_echoes[0].matched_phrase == "ice cream"

    def test_single_content_word_echo(self):
        """A one-word echo flags when that word carries content."""
        result = detect_anti_echo('"Money?" he asks.', '"I have no money left."')
        assert len(result.flagged_echoes) == 1
        assert result.flagged_echoes[0].matched_phrase == "money"

    def test_echo_of_dialogue_ignores_trailing_ooc(self):
        """An [OOC: ...] aside is dropped, but a genuine echo of the spoken
        line in the same message is still caught."""
        result = detect_anti_echo('"No money?" she repeats.', '"I have absolutely no money." [OOC: keep it tense]')
        assert len(result.flagged_echoes) == 1
        assert result.flagged_echoes[0].matched_phrase == "no money"


# ═══════════════════════════════════════════════════════════════════════════════
# FALSE POSITIVES
# ═══════════════════════════════════════════════════════════════════════════════


class TestFalsePositives:
    def test_bare_stopword_question_not_flagged(self):
        """ "You?" copies a word but it's a stopword — no content, no flag."""
        result = detect_anti_echo('"You?" she says.', '"I think you should leave."')
        assert result.flagged_echoes == []

    def test_wh_word_question_not_flagged(self):
        result = detect_anti_echo('"What?" he blinks.', '"What time is it?"')
        assert result.flagged_echoes == []

    def test_incidental_shared_noun_in_long_question(self):
        """A long question that merely reuses one of the user's nouns is below
        the coverage threshold and must not trigger."""
        result = detect_anti_echo(
            '"Should we restock the store room together later?" she wonders.',
            '"I went to the store yesterday."',
        )
        assert result.flagged_echoes == []

    def test_statement_echo_not_flagged(self):
        """Anti-echo is question-gated: a declarative parrot has no '?'."""
        result = detect_anti_echo('"No money," he echoes, nodding.', '"I have no money."')
        assert result.flagged_echoes == []

    def test_original_question_not_flagged(self):
        """A question that shares no contiguous run with the user is fine."""
        result = detect_anti_echo('"Where are you going?" he asks.', '"I got some ice cream."')
        assert result.flagged_echoes == []

    def test_ooc_directive_words_not_in_pool(self):
        """Words the user puts in an [OOC: ...] aside are instructions, not
        in-character speech — the assistant reusing them is compliance. The
        screenshot case: "use" leaked only from "Use the phrase ..."."""
        result = detect_anti_echo(
            '"Do you use shells?" she asks.',
            '"I don\'t have money." [OOC: Use the phrase "a mix of"]',
        )
        assert result.flagged_echoes == []

    def test_user_narration_not_in_pool(self):
        """The pool is the user's dialogue only; words in their narration
        (outside quotes) must not seed an echo flag."""
        result = detect_anti_echo('"Broke?" he asks.', 'I trudge in, broke and tired. "Hey there."')
        assert result.flagged_echoes == []

    def test_message_with_no_dialogue_is_noop(self):
        """A user message that is all narration (no quotes) has no dialogue to
        compare against, so nothing can be flagged as an echo of it."""
        result = detect_anti_echo('"Ice cream?" he blinks.', "I got some ice cream.")
        assert result.flagged_echoes == []

    def test_run_does_not_bridge_two_utterances(self):
        """Each spoken span is its own run, so "ice cream" can't be assembled
        from "ice" in one utterance and "cream" in the next."""
        result = detect_anti_echo('"Ice cream?" he asks.', '"I sell ice." "Cream is extra."')
        assert all(fe.n_words < 2 for fe in result.flagged_echoes)


# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_user_message_is_noop(self):
        assert detect_anti_echo('"Ice cream?" he blinks.', "").flagged_echoes == []

    def test_empty_draft_is_noop(self):
        assert detect_anti_echo("", "I got some ice cream.").flagged_echoes == []

    def test_punctuation_only_user_dialogue_is_noop(self):
        assert detect_anti_echo('"Ice cream?" he blinks.', '"...!?"').flagged_echoes == []

    def test_question_mark_with_trailing_marker(self):
        """ "?!" and trailing closing quotes still register as a question."""
        result = detect_anti_echo('"Ice cream?!" he blinks.', '"I got some ice cream."')
        assert len(result.flagged_echoes) == 1
