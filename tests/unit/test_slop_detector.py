"""
Tests for slop_detector — detect_cliches and format_report integration.

Regression: the report must show the exact matched phrase from the text, not a
canonical/representative form from the variant group.  E.g. if the phrase bank
has ["a dance of", "dancing"] and the text contains "dancing", the report must
say "dancing", not "a dance of".
"""

from __future__ import annotations

from backend.passes.editor.slop_detector import detect_cliches
from backend.passes.editor.audit import format_report, run_audit


# ═══════════════════════════════════════════════════════════════════════════════
# ClicheHit.phrase — always reflects what was found in the text
# ═══════════════════════════════════════════════════════════════════════════════


class TestMatchedPhrase:
    def test_single_word_non_first_variant(self):
        """Single-word variant that is not first in the group stores that word."""
        phrase_bank = [["a dance of", "dancing"]]
        text = "She lets out a short laugh, her eyes dancing with amusement."
        result = detect_cliches(text, phrase_bank)

        assert result.flagged_count == 1
        assert result.flagged_sentences[0].cliches[0].phrase == "dancing"

    def test_first_variant_matched(self):
        """When the first variant itself matches, phrase equals that variant."""
        phrase_bank = [["a dance of", "dancing"]]
        text = "It was a dance of shadows and light."
        result = detect_cliches(text, phrase_bank)

        assert result.flagged_count == 1
        assert result.flagged_sentences[0].cliches[0].phrase == "a dance of"

    def test_two_token_non_first_variant(self):
        """2-token non-first variant is stored correctly."""
        phrase_bank = [["heart racing", "pulse quickening"]]
        text = "Her pulse quickening, she reached for the door."
        result = detect_cliches(text, phrase_bank)

        assert result.flagged_count == 1
        assert result.flagged_sentences[0].cliches[0].phrase == "pulse quickening"

    def test_long_phrase_non_first_variant(self):
        """4+ token non-first variant (trigram path) is stored correctly."""
        phrase_bank = [["tension in the air", "the air is thick with tension"]]
        text = "The air is thick with tension as they face each other."
        result = detect_cliches(text, phrase_bank, threshold=0.4)

        assert result.flagged_count == 1
        assert result.flagged_sentences[0].cliches[0].phrase == "the air is thick with tension"

    def test_unique_cliches_uses_matched_phrases(self):
        """unique_cliches lists the phrases that actually appeared, not group representatives."""
        phrase_bank = [["a dance of", "dancing"]]
        text = "She lets out a short laugh, her eyes dancing with amusement."
        result = detect_cliches(text, phrase_bank)

        assert result.unique_cliches == ["dancing"]


# ═══════════════════════════════════════════════════════════════════════════════
# format_report — displays the matched phrase
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatReportPhrase:
    def test_report_shows_matched_phrase_not_group_representative(self):
        """Regression: the formatted report must show what was in the text."""
        phrase_bank = [["a dance of", "dancing"]]
        text = "She lets out a short laugh, her eyes dancing with amusement."
        report_text = format_report(run_audit(text, phrase_bank))

        assert '"dancing"' in report_text
        assert '"a dance of"' not in report_text

    def test_report_shows_first_variant_when_it_matched(self):
        """When the first variant matched, the report shows it correctly."""
        phrase_bank = [["a dance of", "dancing"]]
        text = "It was a dance of shadows and light."
        report_text = format_report(run_audit(text, phrase_bank))

        assert '"a dance of"' in report_text
