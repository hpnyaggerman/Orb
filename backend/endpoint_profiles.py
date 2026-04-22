"""Endpoint-URL-matched param allowlists.

Some OpenAI-compatible backends reject unknown body fields with HTTP 400
(notably DeepSeek). Orb normally forwards user-configured sampling params
like `min_p`, `top_k`, `repetition_penalty` which these backends don't
understand. When an endpoint URL matches a known profile below, the
LLMClient drops any body key not in `ALWAYS_ALLOWED | PROFILES[match]`.

Unknown endpoints (e.g. local llama.cpp, vLLM) get no profile and pass
through unchanged.
"""

from __future__ import annotations

# Body keys always sent; never subject to allowlist filtering.
ALWAYS_ALLOWED: frozenset[str] = frozenset(
    {"model", "messages", "stream", "tools", "tool_choice"}
)

# URL-substring → set of extra body keys permitted (beyond ALWAYS_ALLOWED).
PROFILES: dict[str, frozenset[str]] = {
    # https://api-docs.deepseek.com/api/create-chat-completion
    "api.deepseek.com": frozenset(
        {
            "temperature",
            "top_p",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "stop",
            "response_format",
            "logprobs",
            "top_logprobs",
            "stream_options",
            "thinking",
        }
    ),
}


def allowlist_for(endpoint_url: str) -> frozenset[str] | None:
    """Return the extra-keys allowlist for a matching profile, or None.

    None means "no profile matched → allow all params through" (current
    behavior for local/unknown backends).
    """
    if not endpoint_url:
        return None
    haystack = endpoint_url.lower()
    for needle, allowed in PROFILES.items():
        if needle in haystack:
            return allowed
    return None
