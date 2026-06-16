"""
anti_echo.py — Detect when the assistant parrots the user's last message back as
an incredulous question.

Some models have a habit of repeating the user's own dialogue as a question:

    H: "I have absolutely no money."
    A: "Absolutely no money?" She repeats.

    H: "I got some ice cream."
    A: He blinks, "Ice cream? You're a grown man."

Unlike every other scanner in this package, this is a *user→assistant* check: it
compares the current draft against the user's immediately-preceding message.

Public API:
    detect_anti_echo(draft, user_message, *, max_question_words=10,
                     min_content_words=1, min_coverage=0.5, short_question_words=4)
    EchoResult, FlaggedEcho  (dataclasses)

Logic:
    - Build the comparison pool from the user's *dialogue* only — the text inside
      their quote spans — after removing ``[OOC: ...]`` asides. The echo we're
      after is the assistant parroting what the *character* said; the user's
      narration and their out-of-character directives ("[OOC: ... Use the phrase
      ...]") are not in-character speech and must not seed a flag. Each spoken
      span is kept as its own token run so a match can't bridge two utterances.
    - Gather interrogative candidates from the draft (sentences ending in ``?``),
      both quoted (the inner text of each quote span) and unquoted (narration).
      Quotes are extracted first so a narration lead-in ("He blinks, ") can't glue
      onto the quoted question.
    - For each candidate, find the longest *contiguous* token run it shares with
      any of the user's spoken spans (an exact copy). Flag it when the run carries
      enough content (non-stopword) words and either the whole question is short or
      the run covers most of it — so bare-stopword questions ("You?", "What?") and
      questions that merely reuse one of the user's nouns don't trigger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text_segmentation import (
    find_quote_spans,
    split_narration_sentences,
    split_sentences,
)

__all__ = [
    "detect_anti_echo",
    "EchoResult",
    "FlaggedEcho",
]


# ---------- public dataclasses ----------


@dataclass
class FlaggedEcho:
    echo: str  # the interrogative sentence flagged
    matched_phrase: str  # the contiguous run copied from the user (normalized)
    n_words: int  # length of that run, in words


@dataclass
class EchoResult:
    flagged_echoes: list[FlaggedEcho] = field(default_factory=list)


# ---------- text processing ----------

_TOKEN_RE = re.compile(r"[a-z0-9']+")

# Out-of-character asides are wrapped in square brackets in this app (the system
# itself emits ``[OOC: ...]`` directives, and users follow the same convention).
# They are instructions *to* the model, not in-character speech — including any
# quotes nested inside them — so they're removed before the user's dialogue is
# read. Matching the innermost brackets and re-running until stable clears nested
# asides without letting a stray inner quote survive.
_OOC_BRACKET_RE = re.compile(r"\[[^\[\]]*\]")

# Trailing closing markers SENT_SPLIT tolerates after a terminator, plus the
# other terminal punctuation that can ride alongside a ``?`` (e.g. "?!", "??").
_TRAILING_MARKERS = " \t\n\"”’'*_)]}>"
_TRAILING_TERMINALS = "!.…"


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _strip_ooc(text: str) -> str:
    """Remove ``[...]`` out-of-character asides, replacing each with a space so the
    words flanking a removed aside don't fuse into one token."""
    prev = None
    while prev != text:
        prev = text
        text = _OOC_BRACKET_RE.sub(" ", text)
    return text


def _ends_with_question(sentence: str) -> bool:
    """True when *sentence* terminates in a question mark, tolerating trailing
    closing markers (quotes, markdown emphasis) and adjacent terminals ("?!")."""
    trimmed = sentence.rstrip(_TRAILING_MARKERS).rstrip(_TRAILING_TERMINALS)
    return trimmed.endswith("?")


# ---------- stopwords / content filter ----------
#
# A small local set — enough for the content-word floor that suppresses
# bare-function-word echoes ("You?", "What?", "Really?"). phrase_repetition keeps
# its own (private) list tuned to n-gram suppression; we don't share it.
_STOPWORDS = frozenset(
    {
        # Articles / determiners / demonstratives
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        # Conjunctions
        "and",
        "or",
        "but",
        "nor",
        "yet",
        "so",
        "if",
        "then",
        "than",
        "as",
        "while",
        # Prepositions
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "into",
        "about",
        # Be / auxiliaries / modals
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        # Pronouns / possessives
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "his",
        "her",
        "its",
        "their",
        "our",
        "your",
        "my",
        "mine",
        "him",
        "them",
        "us",
        "me",
        # Wh-words
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        # Misc fillers
        "not",
        "no",
        "just",
        "only",
        "even",
        "also",
        "very",
        "still",
        "now",
        "there",
        "here",
        "really",
        "right",
        # Common contractions kept whole by _TOKEN_RE
        "i'm",
        "you're",
        "he's",
        "she's",
        "it's",
        "we're",
        "they're",
        "don't",
        "doesn't",
        "didn't",
        "won't",
    }
)


def _longest_common_run(candidate: list[str], user_tokens: list[str]) -> list[str]:
    """Return the longest contiguous sublist of *candidate* that also appears
    contiguously in *user_tokens* (token-level longest common substring)."""
    if not candidate or not user_tokens:
        return []
    best_len = 0
    best_end = 0  # exclusive end index into *candidate*
    prev = [0] * (len(user_tokens) + 1)
    for i, ctok in enumerate(candidate, start=1):
        curr = [0] * (len(user_tokens) + 1)
        for j, utok in enumerate(user_tokens, start=1):
            if ctok == utok:
                run = prev[j - 1] + 1
                curr[j] = run
                if run > best_len:
                    best_len = run
                    best_end = i
        prev = curr
    return candidate[best_end - best_len : best_end]


def _user_dialogue_runs(user_message: str) -> list[list[str]]:
    """The user's spoken dialogue, as one token run per quoted span.

    ``[OOC: ...]`` asides are stripped first (their contents — inner quotes
    included — are directives, not speech), then each remaining quote span
    becomes its own token list so a shared run can't span two separate
    utterances. A message with no quoted dialogue yields no runs, so anti-echo
    has nothing to compare against."""
    cleaned = _strip_ooc(user_message)
    runs: list[list[str]] = []
    for start, end in find_quote_spans(cleaned):
        toks = _tokenize(cleaned[start + 1 : end - 1])
        if toks:
            runs.append(toks)
    return runs


def _longest_run_against_any(candidate: list[str], user_runs: list[list[str]]) -> list[str]:
    """Longest contiguous run *candidate* shares with any single user spoken span."""
    best: list[str] = []
    for toks in user_runs:
        run = _longest_common_run(candidate, toks)
        if len(run) > len(best):
            best = run
    return best


def _interrogative_candidates(draft: str) -> list[str]:
    """All ``?``-ending sentences in *draft*, from both quoted dialogue and
    narration. Quote spans are split apart from their surrounding narration so a
    lead-in clause can't merge into the quoted question."""
    candidates: list[str] = []

    # Quoted dialogue: split each quote's inner text into its own sentences.
    for start, end in find_quote_spans(draft):
        inner = draft[start + 1 : end - 1]
        candidates.extend(split_sentences(inner))

    # Narration: dialogue is stripped, so quoted questions are not double-counted.
    candidates.extend(split_narration_sentences(draft))

    return [s for s in candidates if _ends_with_question(s)]


# ---------- public entry point ----------


def detect_anti_echo(
    draft: str,
    user_message: str,
    *,
    max_question_words: int = 10,
    min_content_words: int = 1,
    min_coverage: float = 0.5,
    short_question_words: int = 4,
) -> EchoResult:
    """Flag questions in *draft* that copy a contiguous run of the user's dialogue.

    Only the user's spoken dialogue (text inside quote spans, with ``[OOC: ...]``
    asides removed) is compared: their narration and out-of-character directives
    are not in-character speech, so the assistant reusing words from them is not
    parroting. A *user_message* with no quoted dialogue produces no flags.

    Args:
        draft: The assistant's current response.
        user_message: The user's immediately-preceding message.
        max_question_words: Skip candidate questions longer than this (the
            parroting pattern is characteristically short).
        min_content_words: Minimum non-stopword tokens the copied run must carry.
        min_coverage: For longer questions, the copied run must cover at least
            this fraction of the question's tokens.
        short_question_words: Questions at or below this token length bypass the
            coverage guard (a short question that copies the user is an echo
            regardless of fraction).
    """
    if not draft or not user_message:
        return EchoResult()

    user_runs = _user_dialogue_runs(user_message)
    if not user_runs:
        return EchoResult()

    flagged: list[FlaggedEcho] = []
    seen: set[str] = set()
    for sentence in _interrogative_candidates(draft):
        key = sentence.strip()
        if key in seen:
            continue
        seen.add(key)

        c_tokens = _tokenize(sentence)
        if not c_tokens or len(c_tokens) > max_question_words:
            continue

        run = _longest_run_against_any(c_tokens, user_runs)
        if not run:
            continue
        if sum(1 for t in run if t not in _STOPWORDS) < min_content_words:
            continue
        if len(c_tokens) > short_question_words and len(run) / len(c_tokens) < min_coverage:
            continue

        flagged.append(FlaggedEcho(echo=key, matched_phrase=" ".join(run), n_words=len(run)))

    return EchoResult(flagged_echoes=flagged)
