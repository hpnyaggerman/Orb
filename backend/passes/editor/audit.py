"""
audit.py — Run all programmatic scanners and produce a consolidated AuditReport.
"""

from __future__ import annotations

from .slop_detector import detect_cliches, DetectionResult
from .opening_monotony import detect_opening_monotony, MonotonyResult
from .template_repetition import detect_template_repetition, TemplateResult
from .contrastive_negation import detect_contrastive_negation


# Data container


class AuditReport:
    __slots__ = (
        "cliche_result",
        "monotony_result",
        "template_result",
        "not_but_result",
    )

    def __init__(
        self,
        cliche_result: DetectionResult,
        monotony_result: MonotonyResult,
        template_result: TemplateResult,
        not_but_result: list[dict] = None,
    ):
        self.cliche_result = cliche_result
        self.monotony_result = monotony_result
        self.template_result = template_result
        self.not_but_result = not_but_result or []

    @classmethod
    def clean(cls) -> "AuditReport":
        """Return a clean report with zero issues (used when audit is disabled)."""
        return cls(
            cliche_result=DetectionResult([], [], 0, 0),
            monotony_result=MonotonyResult([], {}, 0, 0.0),
            template_result=TemplateResult([], {}, 0, 0, 0.0),
            not_but_result=[],
        )

    @property
    def is_clean(self) -> bool:
        return (
            self.cliche_result.flagged_count == 0
            and len(self.monotony_result.flagged_openers) == 0
            and len(self.template_result.flagged_templates) == 0
            and len(self.not_but_result) == 0
        )

    @property
    def total_issues(self) -> int:
        return (
            self.cliche_result.flagged_count
            + len(self.monotony_result.flagged_openers)
            + len(self.template_result.flagged_templates)
            + len(self.not_but_result)
        )


# Run all scanners


def run_audit(
    text: str,
    phrase_bank: list[list[str]],
    cliche_threshold: float = 0.25,
    opener_n_words: int = 1,
    opener_min_consecutive: int = 3,
    template_max_tags: int = 8,
    template_flag_threshold: int = 2,
) -> AuditReport:
    return AuditReport(
        cliche_result=detect_cliches(text, phrase_bank, cliche_threshold),
        monotony_result=detect_opening_monotony(
            text, opener_n_words, opener_min_consecutive
        ),
        template_result=detect_template_repetition(
            text, template_max_tags, template_flag_threshold
        ),
        not_but_result=detect_contrastive_negation(text),
    )


# Format into text report


def format_report(report: AuditReport) -> str:
    if report.is_clean:
        return "*** WRITING AUDIT REPORT ***\n\nAll checks passed — no issues found.\n\n*** END OF REPORT ***"

    sections: list[str] = ["*** WRITING AUDIT REPORT ***\n"]

    # 1. Banned phrases
    cr = report.cliche_result
    if cr.flagged_count > 0:
        lines = ["Banned Phrases"]
        for fs in cr.flagged_sentences:
            for hit in fs.cliches:
                if hit.canonical != hit.variant:
                    lines.append(
                        f'   - "{hit.canonical}" (variant "{hit.variant}") in sentence: {fs.sentence}'
                    )
                else:
                    lines.append(f'   - "{hit.canonical}" in sentence: {fs.sentence}')
        sections.append("\n".join(lines))

    # 2. Repetitive openers
    mr = report.monotony_result
    if mr.flagged_openers:
        lines = ["Repetitive Openers"]
        for fo in mr.flagged_openers:
            lines.append(f'   - "{fo.opener}" ({fo.max_run} consecutive sentences):')
            for s in fo.sentences[:4]:
                lines.append(f"     • {s}")
        sections.append("\n".join(lines))

    # 3. Repetitive templates
    tr = report.template_result
    if tr.flagged_templates:
        lines = ["Repetitive Templates"]
        for ft in tr.flagged_templates:
            lines.append(f'   - "{ft.template}" ({ft.count} sentences):')
            for s in ft.sentences[:4]:
                lines.append(f"     • {s}")
        sections.append("\n".join(lines))

    # 4. Not-but patterns
    if report.not_but_result:
        lines = ["Contrastive Negation Patterns"]
        for nb in report.not_but_result:
            sentence = nb.get("sentence", "")
            x_template = nb.get("x_template", "")
            y_template = nb.get("y_template", "")
            is_parallel = nb.get("is_parallel", False)
            parallel_note = " (parallel structure)" if is_parallel else ""
            lines.append(f'   - Sentence: "{sentence}"{parallel_note}')
            if x_template and y_template:
                lines.append(f"     X: {x_template} -> Y: {y_template}")
        sections.append("\n".join(lines))

    sections.append("\n*** END OF REPORT ***")
    return "\n\n".join(sections)


def _excerpt(text: str, max_len: int = 80) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
