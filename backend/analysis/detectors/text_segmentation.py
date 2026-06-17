"""
text_segmentation.py — Shared paragraph, sentence, and dialogue segmentation
used by all detectors.

Every detector used to carry its own copy of these helpers, and they had silently
drifted apart: some treated "…" as a sentence terminator and some didn't; some
recognized single curly quotes and some didn't; one was missing the
trailing-marker tolerance the others had. This module is the single source of
truth so all detectors split text the same way.

Two splitting functions serve two families of consumers:

- split_sentences — keeps dialogue intact. Used by detectors that need to match
  inside quotes (slop_detector) or analyze clause grammar (contrastive_negation).
- split_narration_sentences — strips dialogue first. Used by detectors that only
  care about narration prose (opening_monotony, template_repetition,
  phrase_repetition).

find_quote_spans and count_sentences support structural_repetition, which
classifies blocks rather than stripping them but still needs the same quote and
terminator definitions.
"""

from __future__ import annotations

import re

__all__ = [
    "PARA_SPLIT",
    "SENT_SPLIT",
    "OPEN_QUOTES",
    "CLOSE_QUOTES",
    "TOGGLE_QUOTES",
    "split_paragraphs",
    "split_sentences",
    "extract_narration",
    "split_narration_sentences",
    "find_quote_spans",
    "count_sentences",
]


# ---------- canonical patterns ----------

# Paragraph break: a blank line, optionally filled with whitespace.
PARA_SPLIT = re.compile(r"\n\s*\n")

# Sentence boundary: a terminator (. ! ? …) followed by whitespace. Trailing
# closing markers (quotes, markdown emphasis, brackets) between the terminator
# and the whitespace are tolerated — e.g. Hiro.* or done." — so a terminator
# hidden behind a markdown marker still splits correctly rather than merging
# adjacent sentences into one.
SENT_SPLIT = re.compile(r"(?<=[.!?…])[\"\u201d\u2019'*_)\]]*\s+")

# Curly directional quotes are unambiguous: left opens, right closes.
OPEN_QUOTES = frozenset({"\u201c", "\u2018"})  # " '
CLOSE_QUOTES = frozenset({"\u201d", "\u2019"})  # " '
# Straight double quote has no direction; we toggle on each occurrence.
# The straight single quote is intentionally excluded from every set so that
# contractions like I'm and don't survive. (Note: U+2019 also doubles as a
# typographic apostrophe, so curly-apostrophe contractions may be clipped —
# an accepted trade-off for recognizing single-quoted dialogue.)
TOGGLE_QUOTES = frozenset({'"'})


# ---------- paragraph / sentence splitting (dialogue preserved) ----------


def split_paragraphs(text: str) -> list[str]:
    """Split on blank-line paragraph breaks, dropping empty paragraphs."""
    return [p for p in PARA_SPLIT.split(text.strip()) if p.strip()]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping dialogue intact.

    Splitting is paragraph-first: a paragraph whose final sentence has no
    detectable terminator can't bleed into the next paragraph.
    """
    sentences: list[str] = []
    for para in split_paragraphs(text):
        for raw in SENT_SPLIT.split(para):
            s = raw.strip()
            if s:
                sentences.append(s)
    return sentences


# ---------- dialogue stripping ----------


def extract_narration(paragraph: str) -> str:
    """Return only the text from paragraph that falls outside any quoted span.

    The caller splits into paragraphs first, so quote state resets at each
    paragraph boundary — an unclosed quote inside one paragraph can't bleed
    into the next. Spaces are inserted where quotes are stripped to prevent
    adjacent words from fusing.
    """
    out: list[str] = []
    inside = False
    prev_was_quote = False

    for ch in paragraph:
        if ch in TOGGLE_QUOTES:
            inside = not inside
            prev_was_quote = True
            continue
        if ch in OPEN_QUOTES:
            inside = True
            prev_was_quote = True
            continue
        if ch in CLOSE_QUOTES:
            inside = False
            prev_was_quote = True
            continue

        if not inside:
            # Insert a space where a quote was stripped, to prevent fusion.
            if prev_was_quote and out and out[-1] not in " \t\n":
                out.append(" ")
            out.append(ch)
        else:
            # Inside quotes — still guard against fusion at the boundary.
            if out and out[-1] not in " \t\n":
                out.append(" ")

        prev_was_quote = False

    return " ".join("".join(out).split())  # Normalize whitespace


def split_narration_sentences(text: str) -> list[str]:
    """Split text into narration sentences, stripping dialogue in the process.

    Splitting is paragraph-aware so quote state and terminators don't bleed
    across paragraph boundaries.
    """
    sentences: list[str] = []
    for para in split_paragraphs(text):
        narration = extract_narration(para).strip()
        if not narration:
            continue
        for raw in SENT_SPLIT.split(narration):
            s = raw.strip()
            if s:
                sentences.append(s)
    return sentences


# ---------- structural helpers ----------


def find_quote_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character spans of every quoted region, inclusive of
    the quote marks themselves.

    Used by detectors that need quote positions rather than stripped narration
    (e.g. structural_repetition, anti_echo). Uses the same quote definitions as
    extract_narration so the two functions agree on what counts as dialogue.
    """
    spans: list[tuple[int, int]] = []
    inside = False
    start = 0
    for i, ch in enumerate(text):
        if ch in TOGGLE_QUOTES:
            if not inside:
                inside = True
                start = i
            else:
                spans.append((start, i + 1))
                inside = False
        elif ch in OPEN_QUOTES:
            if not inside:
                inside = True
                start = i
        elif ch in CLOSE_QUOTES:
            if inside:
                spans.append((start, i + 1))
                inside = False
    return spans


def count_sentences(text: str) -> int:
    """Count the sentences in a block of text.

    Non-empty text with no terminator counts as 1 (a sentence fragment or short
    imperative). Empty text returns 0.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    pieces = [s.strip() for s in SENT_SPLIT.split(stripped) if s.strip()]
    return len(pieces) if pieces else 1
