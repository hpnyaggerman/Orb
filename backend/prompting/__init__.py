"""Deterministic, provider-independent model-facing construction."""

from .base import build_prefix, format_message_with_attachments, group_speaker_label
from .group_context import (
    SPEAKING_CHARACTER,
    context_size_components,
    macro_identity,
    member_macros,
    prefix_is_speaker_scoped,
    render_cast_section,
    resolve_char_in_descriptions,
    tail_carries_identity,
)
from .scene_direction import (
    build_style_injection,
    compute_style_injection_block,
    resolve_mood_fragment_randoms,
)

__all__ = [
    "SPEAKING_CHARACTER",
    "build_prefix",
    "build_style_injection",
    "compute_style_injection_block",
    "context_size_components",
    "format_message_with_attachments",
    "group_speaker_label",
    "macro_identity",
    "member_macros",
    "prefix_is_speaker_scoped",
    "render_cast_section",
    "resolve_char_in_descriptions",
    "resolve_mood_fragment_randoms",
    "tail_carries_identity",
]
