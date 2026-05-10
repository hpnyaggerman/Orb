"""
backend/tts/cache.py — TTS audio caching utilities.

Handles cache path computation, invalidation, metadata sidecars,
and the full synthesize-and-cache workflow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
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


# ---------------------------------------------------------------------------
# Cache eviction
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Defaults — override per-installation if needed.
DEFAULT_MAX_CACHE_BYTES = 500 * 1024 * 1024  # 500 MB
DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def cache_stats() -> dict:
    """Return total file count and bytes used by the TTS cache."""
    total_bytes = 0
    total_files = 0
    if not os.path.isdir(TTS_CACHE_DIR):
        return {"files": 0, "bytes": 0, "mb": 0.0}
    for dirpath, _, filenames in os.walk(TTS_CACHE_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total_bytes += os.path.getsize(fp)
                total_files += 1
            except OSError:
                pass
    return {
        "files": total_files,
        "bytes": total_bytes,
        "mb": round(total_bytes / (1024 * 1024), 2),
    }


def evict_expired(ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
    """Remove cache entries older than *ttl_seconds*. Returns count deleted."""
    if not os.path.isdir(TTS_CACHE_DIR):
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for dirpath, _, filenames in os.walk(TTS_CACHE_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
                    removed += 1
            except OSError:
                pass
    _prune_empty_dirs()
    if removed:
        logger.info(
            "TTS cache TTL eviction: removed %d files (ttl=%ds)", removed, ttl_seconds
        )
    return removed


def evict_lru(max_bytes: int = DEFAULT_MAX_CACHE_BYTES) -> int:
    """Delete oldest files until total cache is under *max_bytes*.

    Returns count of deleted files.
    """
    if not os.path.isdir(TTS_CACHE_DIR):
        return 0
    entries: list[tuple[str, float, int]] = []  # (path, mtime, size)
    total = 0
    for dirpath, _, filenames in os.walk(TTS_CACHE_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                st = os.stat(fp)
                entries.append((fp, st.st_mtime, st.st_size))
                total += st.st_size
            except OSError:
                pass
    if total <= max_bytes:
        return 0
    # Oldest first
    entries.sort(key=lambda e: e[1])
    removed = 0
    for fp, _, sz in entries:
        try:
            os.remove(fp)
        except OSError:
            continue
        total -= sz
        removed += 1
        if total <= max_bytes:
            break
    _prune_empty_dirs()
    if removed:
        logger.info(
            "TTS cache LRU eviction: removed %d files (%.1f MB → %.1f MB budget)",
            removed,
            (total + sum(e[2] for e in entries[:removed])) / (1024 * 1024),
            max_bytes / (1024 * 1024),
        )
    return removed


def invalidate_cache_for_conversation(cid: str) -> bool:
    """Remove cached TTS audio for a single conversation. Returns True if existed."""
    _cache_dir = os.path.join(TTS_CACHE_DIR, cid)
    if os.path.isdir(_cache_dir):
        shutil.rmtree(_cache_dir)
        return True
    return False


def run_eviction_cycle(
    max_bytes: int = DEFAULT_MAX_CACHE_BYTES,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict:
    """Run a full eviction cycle: TTL purge first, then LRU if still over budget.

    Returns a summary dict.
    """
    ttl_removed = evict_expired(ttl_seconds)
    lru_removed = evict_lru(max_bytes)
    stats = cache_stats()
    return {
        "ttl_removed": ttl_removed,
        "lru_removed": lru_removed,
        "stats": stats,
    }


def _prune_empty_dirs() -> None:
    """Remove leaf directories under TTS_CACHE_DIR that have no files."""
    if not os.path.isdir(TTS_CACHE_DIR):
        return
    for dirpath, dirnames, filenames in os.walk(TTS_CACHE_DIR, topdown=False):
        # Only prune sub-directories, not TTS_CACHE_DIR itself
        if dirpath == TTS_CACHE_DIR:
            continue
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


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
