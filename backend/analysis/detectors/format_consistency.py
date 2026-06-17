"""format_consistency.py — Keep RP markup style consistent across messages.

RP output drifts between *formatting conventions*: one message wraps action in
``*asterisks*`` and leaves speech bare, the next leaves action as bare prose and
quotes its speech. This module detects the convention of recent messages and
deterministically rewrites a new draft's markup to match — no LLM involved.

The problem is modelled as two **independent axes**, each detected by coverage
fraction rather than mere presence (so an occasional emphasized word or italic
thought inside otherwise-bare prose does not flip a whole message):

- Dialogue axis — is speech ``QUOTED`` ("…") or ``BARE``?
- Narration axis — is action/narration ``ASTERISK`` (*…*) or ``BARE`` prose?

A span's role (dialogue vs narration) is fixed by its markup plus the message's
convention, so once the axes are known the rewrite is mechanical. When an axis
can't be classified confidently — or the baseline window disagrees — that axis
is left alone, so the safe failure mode is a byte-identical no-op.

Public API:
    classify_axes(text) -> AxisStyle
    baseline_axes(messages) -> AxisStyle
    normalize_format(draft, target) -> str
    normalize_to_baseline(draft, baseline_messages, *, enabled) -> (str, FormatDriftReport)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from .text_segmentation import extract_block_spans, split_paragraphs

__all__ = [
    "Dialogue",
    "Narration",
    "AxisStyle",
    "FormatDriftReport",
    "classify_axes",
    "baseline_axes",
    "normalize_format",
    "normalize_to_baseline",
]


class Dialogue(str, Enum):
    QUOTED = "quoted"
    BARE = "bare"
    UNKNOWN = "unknown"


class Narration(str, Enum):
    ASTERISK = "asterisk"
    BARE = "bare"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AxisStyle:
    dialogue: Dialogue
    narration: Narration

    def label(self) -> str:
        return f"dialogue={self.dialogue.value}, narration={self.narration.value}"


@dataclass
class FormatDriftReport:
    """What the normalizer decided. ``changed`` is True only when the draft text
    was actually rewritten."""

    source: AxisStyle | None
    target: AxisStyle | None
    changed: bool
    note: str


# ---------- thresholds ----------
# Coverage fractions for the narration axis. Between LOW and HIGH the message is
# genuinely mixed, so we report UNKNOWN and leave it untouched.
_NARR_HIGH = 0.6  # >= this fraction of narration chars inside *asterisks* -> ASTERISK
_NARR_LOW = 0.25  # <= this -> BARE


# ---------- inline emphasis vs block narration ----------


def _emphasis_inner(raw: str) -> str:
    """Strip the surrounding * / _ markers from an emphasis span's raw text."""
    core = raw.strip()
    if len(core) >= 2 and core[0] in "*_" and core[-1] == core[0]:
        return core[1:-1].strip()
    return core.strip("*_ ").strip()


def _is_inline_emphasis(inner: str) -> bool:
    """A short, lowercase, or single-word emphasis span is treated as inline
    emphasis (an emphasized word or interjection) rather than block-level action
    narration. Such spans are always preserved and never count toward the
    narration axis. Clause-like spans (capitalized multi-word, or carrying a
    sentence terminator) are treated as narration markup."""
    words = inner.split()
    if len(words) <= 1:
        return True
    if inner[:1].islower():
        return True
    return False


# ---------- classification ----------


def classify_axes(text: str) -> AxisStyle:
    """Classify *text* on the dialogue and narration axes by coverage fraction."""
    speech_chars = 0
    block_emph_chars = 0
    bare_chars = 0

    for para in split_paragraphs(text):
        for typ, s, e in extract_block_spans(para):
            length = len(para[s:e].strip())
            if length == 0:
                continue
            if typ == "SPEECH":
                speech_chars += length
            elif typ == "EMPHASIS":
                if _is_inline_emphasis(_emphasis_inner(para[s:e])):
                    continue  # inline emphasis is orthogonal to both axes
                block_emph_chars += length
            else:  # NARRATION (bare)
                bare_chars += length

    # Narration axis: of the non-dialogue prose, how much sits inside asterisks?
    narr_total = block_emph_chars + bare_chars
    if narr_total == 0:
        narration = Narration.UNKNOWN  # no narration to judge (e.g. pure dialogue)
    else:
        ratio = block_emph_chars / narr_total
        if ratio >= _NARR_HIGH:
            narration = Narration.ASTERISK
        elif ratio <= _NARR_LOW:
            narration = Narration.BARE
        else:
            narration = Narration.UNKNOWN

    # Dialogue axis: quotes are unambiguous, so any real quoted span -> QUOTED.
    # Otherwise dialogue can only be read as BARE when narration is asterisk-marked
    # (the asterisk convention, where the bare runs are the spoken lines).
    if speech_chars > 0:
        dialogue = Dialogue.QUOTED
    elif narration == Narration.ASTERISK and bare_chars > 0:
        dialogue = Dialogue.BARE
    else:
        dialogue = Dialogue.UNKNOWN

    return AxisStyle(dialogue=dialogue, narration=narration)


def _stable(values: list[Enum], unknown: Enum) -> Enum:
    """The agreed value across a baseline window, or *unknown* if it isn't stable.

    Confident (non-unknown) classifications must form a clear majority. A single
    prior message is trusted (early in a conversation there is nothing else)."""
    confident = [v for v in values if v != unknown]
    if not confident:
        return unknown
    val, cnt = Counter(confident).most_common(1)[0]
    if len(confident) == 1 or (cnt >= 2 and cnt / len(confident) >= 0.6):
        return val
    return unknown


def baseline_axes(messages: list[str]) -> AxisStyle:
    """Derive the target axes from recent assistant messages. Each axis is set
    only when the window agrees on it; otherwise it stays UNKNOWN (not enforced)."""
    styles = [classify_axes(m) for m in messages if m and m.strip()]
    return AxisStyle(
        dialogue=_stable([s.dialogue for s in styles], Dialogue.UNKNOWN),  # type: ignore[arg-type]
        narration=_stable([s.narration for s in styles], Narration.UNKNOWN),  # type: ignore[arg-type]
    )


# ---------- rewriting ----------

_TERMINATORS = ".!?…,;:"


def _role(typ: str, raw: str, src_dialogue: Dialogue) -> str:
    """Map a block span to its semantic role under the source convention."""
    if typ == "SPEECH":
        return "DIALOGUE"
    if typ == "EMPHASIS":
        return "EMPHASIS_INLINE" if _is_inline_emphasis(_emphasis_inner(raw)) else "NARRATION"
    # bare NARRATION span
    if src_dialogue == Dialogue.BARE:
        return "DIALOGUE"  # asterisk convention: bare runs are spoken lines
    return "NARRATION"


def _split_ws(raw: str) -> tuple[str, str, str]:
    """(leading_ws, core, trailing_ws) so a transform touches only the core."""
    lead = raw[: len(raw) - len(raw.lstrip())]
    trail = raw[len(raw.rstrip()) :]
    return lead, raw.strip(), trail


def _strip_quotes(raw: str) -> str:
    lead, core, trail = _split_ws(raw)
    if len(core) >= 2:
        core = core[1:-1].strip()
    return f"{lead}{core}{trail}"


def _wrap_quotes(raw: str) -> str:
    lead, core, trail = _split_ws(raw)
    if not core:
        return raw
    core = core.replace("*", "").replace("_", "").strip()
    return f'{lead}"{core}"{trail}'


def _wrap_asterisks(raw: str) -> str:
    lead, core, trail = _split_ws(raw)
    if not core:
        return raw
    core = core.replace("*", "").replace("_", "").strip()
    return f"{lead}*{core}*{trail}"


def _strip_block_emphasis(raw: str) -> str:
    """Drop the * / _ markers of a block-level emphasis span, turning it into bare
    prose. A terminal period is added when the freed clause ends on a word so the
    next segment doesn't fuse onto it."""
    lead, core, trail = _split_ws(raw)
    inner = _emphasis_inner(raw)
    if inner and inner[-1].isalnum():
        inner += "."
    return f"{lead}{inner}{trail}"


def _rewrite_paragraph(
    para: str,
    src: AxisStyle,
    target_dialogue: Dialogue | None,
    target_narration: Narration | None,
) -> str:
    """Rewrite one paragraph. ``target_*`` is None for an axis that isn't changing.

    ``wrap`` transforms (BARE -> marked) group consecutive same-role spans — plus
    any inline emphasis between them — so a single utterance/clause becomes one
    wrapped unit rather than several fragments."""
    spans = extract_block_spans(para)
    out: list[str] = []
    i = 0
    n = len(spans)
    while i < n:
        typ, s, e = spans[i]
        raw = para[s:e]
        role = _role(typ, raw, src.dialogue)

        if role == "DIALOGUE" and target_dialogue is not None:
            if target_dialogue == Dialogue.BARE and typ == "SPEECH":
                out.append(_strip_quotes(raw))
                i += 1
                continue
            if target_dialogue == Dialogue.QUOTED and typ == "NARRATION":
                run_end = _group_run(spans, i, src, "DIALOGUE", para)
                out.append(_wrap_quotes(para[s : spans[run_end][2]]))
                i = run_end + 1
                continue

        if role == "NARRATION" and target_narration is not None:
            if target_narration == Narration.BARE and typ == "EMPHASIS":
                out.append(_strip_block_emphasis(raw))
                i += 1
                continue
            if target_narration == Narration.ASTERISK and typ == "NARRATION":
                run_end = _group_run(spans, i, src, "NARRATION", para)
                out.append(_wrap_asterisks(para[s : spans[run_end][2]]))
                i = run_end + 1
                continue

        out.append(raw)
        i += 1
    return "".join(out)


def _group_run(spans, i, src: AxisStyle, role: str, para: str) -> int:
    """Index of the last span in the maximal run starting at *i* that has the
    given role (inline emphasis is absorbed into the run)."""
    j = i
    while j + 1 < len(spans):
        t2, s2, e2 = spans[j + 1]
        r2 = _role(t2, para[s2:e2], src.dialogue)
        if r2 == role or r2 == "EMPHASIS_INLINE":
            j += 1
        else:
            break
    return j


def normalize_format(draft: str, target: AxisStyle) -> str:
    """Rewrite *draft* so its markup matches *target*, changing only the axes that
    differ and can be resolved safely. Returns *draft* unchanged when there is
    nothing confident to do."""
    src = classify_axes(draft)

    change_dialogue = (
        target.dialogue != Dialogue.UNKNOWN and src.dialogue != Dialogue.UNKNOWN and target.dialogue != src.dialogue
    )
    change_narration = (
        target.narration != Narration.UNKNOWN and src.narration != Narration.UNKNOWN and target.narration != src.narration
    )

    # Wrapping bare prose in asterisks means re-reading which bare text is
    # narration — only safe when the dialogue axis tells us (quoted convention).
    if change_narration and target.narration == Narration.ASTERISK and src.dialogue != Dialogue.QUOTED:
        change_narration = False

    if not (change_dialogue or change_narration):
        return draft

    td = target.dialogue if change_dialogue else None
    tn = target.narration if change_narration else None

    # Split on paragraph breaks while keeping the original separators, so blank-line
    # spacing survives intact (quote/emphasis state already resets per paragraph).
    pieces = re.split(r"(\n\s*\n)", draft)
    rebuilt = [
        piece if (idx % 2 == 1 or not piece.strip()) else _rewrite_paragraph(piece, src, td, tn)
        for idx, piece in enumerate(pieces)
    ]
    return "".join(rebuilt)


def normalize_to_baseline(
    draft: str,
    baseline_messages: list[str] | None,
    *,
    enabled: bool,
) -> tuple[str, FormatDriftReport]:
    """Entry point: hold *draft* to the convention of *baseline_messages*.

    Returns the (possibly unchanged) text and a small report for logging. A no-op
    — disabled, no baseline, ambiguous axes, or already consistent — returns the
    draft byte-for-byte."""
    if not enabled:
        return draft, FormatDriftReport(None, None, False, "disabled")
    if not draft or not draft.strip() or not baseline_messages:
        return draft, FormatDriftReport(None, None, False, "no baseline")

    target = baseline_axes(baseline_messages)
    if target.dialogue == Dialogue.UNKNOWN and target.narration == Narration.UNKNOWN:
        return draft, FormatDriftReport(None, target, False, "baseline unstable")

    source = classify_axes(draft)
    new_text = normalize_format(draft, target)
    changed = new_text != draft
    note = "normalized" if changed else "already consistent"
    return new_text, FormatDriftReport(source, target, changed, note)
