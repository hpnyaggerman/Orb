"""Shared utility helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .domain_types import AgentLane
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


#: The sampler/budget fields a settings row carries for a lane, in the order the
#: endpoint editor shows them.
_HYPERPARAM_KEYS = (
    "temperature",
    "max_tokens",
    "top_p",
    "min_p",
    "top_k",
    "repetition_penalty",
)


def extract_hyperparams(
    settings: Mapping[str, Any],
    *,
    lane: AgentLane = "writer",
    token_floor: int | None = None,
    defaults: Mapping[str, Any] | None = None,
) -> dict:
    """Extract LLM hyperparameters from a settings dict for the lane making the call.

    The agent lane reads each key's ``agent_`` twin. ``get_settings`` overlays those
    from the agent endpoint's own model config, and only when a separate lane
    resolves, so single-model mode falls through to the writer's values -- which is
    the same endpoint it is calling. Passing the writer's lane to an agent call is
    not a harmless default: it sends one endpoint's preset to another. The fallback
    is per key rather than whole-row only as a guard for partial mappings; the six
    columns behind these keys are all NOT NULL, so a resolved agent lane carries
    every twin and an unresolved one carries none.

    ``token_floor`` is what the call needs to answer in full. The configured budget
    may only *raise* it: a budget is a reply-length preference, and a short-reply
    preset is a normal setting, while the floor is what the call needs to answer at
    all -- so honoring a smaller one would truncate the reply mid-answer and turn a
    sampling preference into a silent failure. Every call whose whole answer has to
    fit in one reply (a forced tool call, a constrained-decoding call) passes one;
    passes that stream prose take the setting as-is and leave it unset.

    Optionally fills in *defaults* for any keys not present in settings. Note that
    both ``settings`` and ``model_configs`` declare all six columns NOT NULL, so
    *defaults* only ever fires for a partial mapping, never for a real row -- it is
    not a way to spell a minimum, which is what ``token_floor`` is for.
    """
    prefix = "agent_" if lane == "agent" else ""
    params: dict[str, Any] = {}
    for key in _HYPERPARAM_KEYS:
        value = settings.get(f"{prefix}{key}") if prefix else None
        if value is None:
            value = settings.get(key)
        if value is not None:
            params[key] = value
    if defaults:
        for k, v in defaults.items():
            if k not in params:
                params[k] = v
    if token_floor is not None:
        params["max_tokens"] = max(token_floor, int(params.get("max_tokens") or 0))
    return params


def agent_lane_max_tokens(settings: Mapping[str, Any], *, floor: int) -> int:
    """The agent lane's reply budget for a call that needs at least *floor* tokens.

    The lane cascade and the floor rule are ``extract_hyperparams``'; this is the
    spelling for a caller that sets its own samplers and wants only the budget.
    """
    return int(extract_hyperparams(settings, lane="agent", token_floor=floor)["max_tokens"])


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
