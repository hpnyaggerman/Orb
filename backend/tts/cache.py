"""
backend/tts/cache.py — TTS audio caching utilities.

Handles cache path computation, invalidation, metadata sidecars,
and the full synthesize-and-cache workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import TTSAdapter

TTS_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tts_cache")


def cache_media_type(profile: dict) -> tuple[str, str]:
    """Return the expected cached media type and extension for a voice profile."""
    if profile.get("backend") == "kokoro":
        return "audio/wav", "wav"
    return "audio/mpeg", "mp3"


def format_script(chunks: list) -> str:
    """Format speakable chunks into a human-readable speech script."""
    lines = []
    for c in chunks:
        if not c.text.strip():
            continue
        parts = []
        if c.pause_before_ms >= 500:
            parts.append(f"[...{c.pause_before_ms}ms]")
        elif c.pause_before_ms >= 200:
            parts.append(f"[{c.pause_before_ms}ms]")
        parts.append(c.text)
        if c.pause_after_ms >= 500:
            parts.append(f"[...{c.pause_after_ms}ms]")
        elif c.pause_after_ms >= 200:
            parts.append(f"[{c.pause_after_ms}ms]")
        if c.emotion and c.emotion != "neutral":
            parts.append(f"({c.emotion})")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def cache_path(cid: str, msg_id: int, profile: dict, content: str = "") -> str:
    """Cache path keyed by message content and voice configuration."""
    media_type, ext = cache_media_type(profile)
    fingerprint = hashlib.md5(
        f"{profile.get('backend', '')}|{profile.get('voice_id', '')}|"
        f"{profile.get('language', '')}|{profile.get('rate', '')}|{profile.get('pitch', '')}|"
        f"{profile.get('api_url', '')}|"
        f"{profile.get('model', '')}|{media_type}|{content}".encode(),
        usedforsecurity=False,
    ).hexdigest()[:8]
    return os.path.join(TTS_CACHE_DIR, cid, f"{msg_id}_{fingerprint}.{ext}")


def cache_meta_path(audio_path: str) -> str:
    """Sidecar path for TTS extraction metadata."""
    return audio_path + ".json"


def metadata_headers(metadata: dict) -> dict[str, str]:
    """Expose extraction debug data without changing the audio response body."""
    text = metadata.get("extracted_text", "") or ""
    return {
        "X-Orb-TTS-Extraction-Method": metadata.get("extraction_method", "") or "",
        "X-Orb-TTS-Extracted-Text": urllib.parse.quote(text[:4000]),
    }


def invalidate_cache_for_card(conv_ids: list[str]) -> None:
    """Remove cached TTS audio for all conversations using a character card."""
    for cid in conv_ids:
        _cache_dir = os.path.join(TTS_CACHE_DIR, cid)
        if os.path.isdir(_cache_dir):
            shutil.rmtree(_cache_dir)


async def synthesize_and_cache(
    cid: str,
    msg_id: int,
    profile: dict,
    content: str,
    adapter: TTSAdapter,
) -> tuple[bytes, str, dict[str, str], str]:
    """Synthesize TTS audio, cache it, and return result data.

    Returns (audio_bytes, content_type, metadata, cache_file_path).

    Raises ValueError when synthesis produces no audio.
    """
    from .regex_extractor import regex_extract

    # Algorithm path — zero LLM, zero latency
    chunks = regex_extract(
        text=content,
        backend_type=profile["backend"],
        supports_emotion_tags=adapter.supports_emotion_tags,
    )

    md: dict = {
        "extraction_method": "regex",
        "extracted_text": format_script(chunks),
    }

    # Synthesize audio
    result = await adapter.synthesize(
        chunks=chunks,
        voice_id=profile.get("voice_id", "en-US-JennyNeural"),
        language=profile.get("language", "en-US"),
        rate=profile.get("rate", 1.0),
        pitch=profile.get("pitch", 1.0),
        api_url=profile.get("api_url", ""),
        api_key=profile.get("api_key", "") or None,
        model=profile.get("model", ""),
    )

    if not result.audio_bytes:
        raise ValueError("TTS synthesis produced no audio")

    # Cache the audio and extraction metadata
    _cp = cache_path(cid, msg_id, profile, content)
    os.makedirs(os.path.dirname(_cp), exist_ok=True)
    with open(_cp, "wb") as f:
        f.write(result.audio_bytes)
    with open(cache_meta_path(_cp), "w", encoding="utf-8") as f:
        json.dump(md, f, ensure_ascii=False)

    return result.audio_bytes, result.content_type, md, _cp
