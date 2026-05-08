"""
pipeline_utils.py — Shared helpers for the pipeline passes and orchestrator.
"""

from __future__ import annotations

from typing import List, Optional

from .llm_client import LLMClient
from .prompt_builder import replace_placeholders


class _PlaceholderClient(LLMClient):
    """Thin wrapper that replaces {{user}}/{{char}} in messages before completion."""

    def __init__(self, inner: LLMClient, user_name: str, char_name: str) -> None:
        self._inner = inner
        self._user_name = user_name
        self._char_name = char_name

    def abort(self) -> None:
        self._inner.abort()

    @property
    def is_aborted(self) -> bool:
        return self._inner.is_aborted

    async def complete(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        tool_choice: dict | str | None = None,
        **params,
    ):
        msgs = _replace_in_messages(messages, self._user_name, self._char_name)
        async for item in self._inner.complete(
            msgs, model, tools=tools, tool_choice=tool_choice, **params
        ):
            yield item


def _replace_in_messages(
    messages: list[dict], user_name: str, char_name: str
) -> list[dict]:
    result = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            content = replace_placeholders(content, user_name, char_name)
        elif isinstance(content, list):
            content = [
                (
                    {
                        **part,
                        "text": replace_placeholders(
                            part["text"], user_name, char_name
                        ),
                    }
                    if part.get("type") == "text"
                    else part
                )
                for part in content
            ]
        result.append({**msg, "content": content})
    return result


def extract_hyperparams(settings: dict, *, defaults: dict | None = None) -> dict:
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


def build_multimodal_content(
    text: str, attachments: Optional[List[dict]] = None
) -> str | list:
    """Wrap *text* (and optional image attachments) into a multimodal content list.

    Returns a plain string when there are no attachments, or a list of content
    parts suitable for vision-capable LLM endpoints.
    """
    if not attachments:
        return text
    parts: list = [{"type": "text", "text": text}]
    for att in attachments:
        mime = att.get("mime_type", att.get("mime", "image/jpeg"))
        b64 = att.get("data_b64", att.get("b64", ""))
        if not b64:
            continue
        url = f"data:{mime};base64,{b64}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts
