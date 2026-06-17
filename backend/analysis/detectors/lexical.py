"""
lexical.py — Shared word-level helpers used across the prose-quality detectors.

These are the operations that work on individual words and token lists:
tokenizing text, normalizing a single word, sliding an n-gram window, and the
content-word floor (a match is only worth flagging if it carries enough
non-stopword words). Detectors used to carry their own copies of these — the
tokenizer regex, the stopword list, the n-gram helper — and the copies had
silently drifted apart. This module is the single source of truth so every
detector tokenizes, normalizes, and judges "content" the same way.

Note on tokenizers: slop_detector and contrastive_negation deliberately keep
their own tokenizers — slop_detector needs phrase casing and punctuation
boundaries, contrastive_negation needs punctuation tokens for clause grammar —
so they don't use tokenize()/STOPWORDS here. They do share ngrams(), which is a
pure sequence operation independent of how the tokens were produced.

Public API:
    TOKEN_RE                — the word pattern ([a-z0-9']+)
    tokenize(text)          — lowercase word tokens
    normalize_word(word)    — lowercase a word, stripped to [a-z0-9']
    ngrams(tokens, n)       — sliding window of n-word tuples over a token list
    STOPWORDS               — function/filler words excluded from the content-word floor
    count_content_words(ts) — number of tokens in ts that are not stopwords
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

__all__ = [
    "TOKEN_RE",
    "tokenize",
    "normalize_word",
    "ngrams",
    "STOPWORDS",
    "count_content_words",
]


# ---------- tokenization ----------

# Lowercase word runs; the apostrophe is kept so contractions stay as single
# tokens (don't, it's) and line up with the contraction entries in STOPWORDS.
TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Lowercase text and return its word tokens."""
    return TOKEN_RE.findall(text.lower())


def normalize_word(word: str) -> str:
    """Lowercase a single word and strip everything except a-z, 0-9, and
    apostrophes — the same alphabet TOKEN_RE matches.

    Shared by the opener and template detectors, which key on individual
    space-split words rather than re-running the tokenizer, so they need the
    same normalized token form.
    """
    return re.sub(r"[^a-z0-9']", "", word.lower())


# ---------- n-grams ----------


def ngrams(tokens: list[str], n: int) -> Iterator[tuple[str, ...]]:
    """Yield every contiguous n-word window of tokens as a tuple.

    Yields nothing when there are fewer than n tokens. Callers that need a set
    of distinct n-grams can wrap the result in set(); callers that need every
    occurrence (including repeats) can iterate directly.
    """
    for i in range(len(tokens) - n + 1):
        yield tuple(tokens[i : i + n])


# ---------- stopwords / content filter ----------
#
# Function words and fillers that don't count toward the content-word floor.
# Without this, bare-function-word matches like "You?", "What?", "in the air",
# or "I don't know" could trigger a flag on their own. Shared by anti_echo
# (copied-run floor) and phrase_repetition (n-gram floor).
STOPWORDS = frozenset(
    {
        # Articles / determiners / demonstratives / quantifiers
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "some",
        "any",
        "each",
        "every",
        "all",
        "both",
        "either",
        "neither",
        "such",
        "another",
        "other",
        "same",
        "own",
        "much",
        "many",
        "more",
        "most",
        "less",
        "least",
        "few",
        "fewer",
        "several",
        "enough",
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
        "because",
        "since",
        "though",
        "although",
        "unless",
        "until",
        "till",
        "whereas",
        "whether",
        "whenever",
        "wherever",
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
        "onto",
        "about",
        "off",
        "out",
        "up",
        "down",
        "over",
        "under",
        "above",
        "below",
        "between",
        "among",
        "through",
        "throughout",
        "during",
        "before",
        "after",
        "against",
        "without",
        "within",
        "upon",
        "toward",
        "towards",
        "across",
        "along",
        "behind",
        "beside",
        "besides",
        "near",
        "around",
        "amid",
        "amongst",
        "beneath",
        "beyond",
        "per",
        "via",
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
        "ought",
        "having",
        "get",
        "gets",
        "got",
        "getting",
        # Pronouns / possessives / reflexives
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
        "yours",
        "hers",
        "ours",
        "theirs",
        "myself",
        "yourself",
        "yourselves",
        "himself",
        "herself",
        "itself",
        "oneself",
        "ourselves",
        "themselves",
        "one",
        "ones",
        "someone",
        "somebody",
        "something",
        "anyone",
        "anybody",
        "anything",
        "everyone",
        "everybody",
        "everything",
        "nobody",
        "nothing",
        "none",
        "whoever",
        "whatever",
        "whichever",
        "whomever",
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
        # Misc fillers / adverbs
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
        "too",
        "quite",
        "rather",
        "almost",
        "already",
        "indeed",
        "perhaps",
        "maybe",
        "anyway",
        "instead",
        "however",
        "moreover",
        "thus",
        "hence",
        "therefore",
        "else",
        "ever",
        "never",
        "always",
        "often",
        "sometimes",
        "usually",
        "again",
        "once",
        "twice",
        "well",
        "okay",
        "ok",
        "yes",
        "yeah",
        "yep",
        "nope",
        "oh",
        "ah",
        "uh",
        "um",
        "hmm",
        "hey",
        "please",
        "actually",
        "literally",
        "basically",
        "simply",
        "merely",
        # Common contractions kept whole by TOKEN_RE
        "i'm",
        "you're",
        "he's",
        "she's",
        "it's",
        "we're",
        "they're",
        "i've",
        "you've",
        "we've",
        "they've",
        "i'll",
        "you'll",
        "he'll",
        "she'll",
        "we'll",
        "they'll",
        "i'd",
        "you'd",
        "he'd",
        "she'd",
        "we'd",
        "they'd",
        "don't",
        "doesn't",
        "didn't",
        "won't",
        "can't",
        "cannot",
        "couldn't",
        "wouldn't",
        "shouldn't",
        "mustn't",
        "isn't",
        "aren't",
        "wasn't",
        "weren't",
        "haven't",
        "hasn't",
        "hadn't",
        "ain't",
        "let's",
        "that's",
        "there's",
        "here's",
        "what's",
        "who's",
        "where's",
        "when's",
        "why's",
        "how's",
    }
)


def count_content_words(tokens: Iterable[str]) -> int:
    """Count how many tokens are content words (i.e. not stopwords)."""
    return sum(1 for t in tokens if t not in STOPWORDS)
