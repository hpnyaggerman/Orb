"""Shared utility helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .llm_types import ContentPart

#: Heuristic characters-per-token ratio used for rough context-size estimates.
#: This is the one convention referenced throughout (see AGENTS.md → Context
#: Management); keep all chars→token estimation going through ``estimate_tokens``
#: rather than re-spelling the constant.
CHARS_PER_TOKEN = 4


def estimate_tokens(chars: int) -> int:
    """Rough token estimate from a character count (min 1 for any non-empty text)."""
    if chars <= 0:
        return 0
    return max(1, round(chars / CHARS_PER_TOKEN))


def scrub_log(value: object) -> str:
    """Sanitize a value for safe inclusion in a log message (CWE-117).

    User-controlled values can carry newlines or carriage returns that would
    otherwise let an attacker forge extra log lines. Coerce to text and strip
    the line breaks so each value stays confined to a single log record.
    """
    return str(value).replace("\r", "").replace("\n", "")


def extract_hyperparams(settings: Mapping[str, Any], *, defaults: Mapping[str, Any] | None = None) -> dict:
    """Extract LLM hyperparameters from a settings dict.

    Optionally fills in *defaults* for any keys not present in settings.
    """
    keys = [
        "temperature",
        "max_tokens",
        "top_p",
        "min_p",
        "top_k",
        "repetition_penalty",
    ]
    params = {k: v for k in keys if (v := settings.get(k)) is not None}
    if defaults:
        for k, v in defaults.items():
            if k not in params:
                params[k] = v
    return params


def build_multimodal_content(text: str, attachments: Sequence[Mapping[str, Any]] | None = None) -> str | list[ContentPart]:
    """Wrap *text* (and optional image attachments) into a multimodal content list.

    Returns a plain string when there are no attachments, or a list of content
    parts suitable for vision-capable LLM endpoints.
    """
    if not attachments:
        return text
    parts: list[ContentPart] = [{"type": "text", "text": text}]
    for att in attachments:
        mime = att.get("mime_type", att.get("mime", "image/jpeg"))
        b64 = att.get("data_b64", att.get("b64", ""))
        if not b64:
            continue
        url = f"data:{mime};base64,{b64}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


_KEY_NOISE = re.compile(r"[^a-z0-9]")


def fold_key(value: str) -> str:
    """Reduce a fragment id or tool-argument key to its letters and digits, lowercased.

    A fragment id reaches the model as a tool-schema property name and comes
    back however the model or its server spells it: hyphens as underscores,
    separators dropped, case changed. Two names with the same fold denote the
    same field everywhere Orb compares such names, which is also why an id that
    differs from an existing one only by case or separators is refused.
    """
    return _KEY_NOISE.sub("", value.lower())


def match_folded(name: str, candidates: Iterable[str]) -> str | None:
    """The candidate *name* denotes: an exact match, else the first whose fold equals its fold, else ``None``."""
    pool = list(candidates)
    if name in pool:
        return name
    wanted = fold_key(name)
    return next((c for c in pool if fold_key(c) == wanted), None)


def folded_collisions(ids: Iterable[str]) -> list[tuple[str, str]]:
    """Pairs ``(first, later)`` of ids sharing a fold, each later id against the first one seen."""
    first: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    for fid in ids:
        key = fold_key(fid)
        if key in first:
            pairs.append((first[key], fid))
        else:
            first[key] = fid
    return pairs
