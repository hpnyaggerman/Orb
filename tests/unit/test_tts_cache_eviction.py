"""
Unit tests for TTS cache eviction functions.

Tests cache_stats, evict_expired, evict_lru, invalidate_cache_for_conversation,
run_eviction_cycle, and _prune_empty_dirs using tmp_path fixtures.
"""

from __future__ import annotations

import os
import time

import pytest

from backend.tts.cache import (
    DEFAULT_MAX_CACHE_BYTES,
    DEFAULT_TTL_SECONDS,
    _prune_empty_dirs,
    cache_stats,
    evict_expired,
    evict_lru,
    invalidate_cache_for_conversation,
    run_eviction_cycle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    """Point TTS_CACHE_DIR at a temp directory for every test."""
    cache_root = tmp_path / "tts_cache"
    cache_root.mkdir()
    monkeypatch.setattr("backend.tts.cache.TTS_CACHE_DIR", str(cache_root))
    return cache_root


def _write_file(cache_root, cid, filename, content=b"audio", age_seconds=0):
    """Helper: create a cache file under a conversation dir."""
    conv_dir = cache_root / cid
    conv_dir.mkdir(exist_ok=True)
    fp = conv_dir / filename
    fp.write_bytes(content)
    if age_seconds:
        mtime = time.time() - age_seconds
        os.utime(str(fp), (mtime, mtime))
    return fp


# ---------------------------------------------------------------------------
# cache_stats
# ---------------------------------------------------------------------------


class TestCacheStats:
    def test_empty_cache(self, _isolate_cache_dir):
        result = cache_stats()
        assert result == {"files": 0, "bytes": 0, "mb": 0.0}

    def test_counts_files_and_bytes(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "a.wav", b"x" * 100)
        _write_file(_isolate_cache_dir, "conv1", "b.wav", b"x" * 200)
        _write_file(_isolate_cache_dir, "conv2", "c.wav", b"x" * 300)

        result = cache_stats()
        assert result["files"] == 3
        assert result["bytes"] == 600
        assert result["mb"] == round(600 / (1024 * 1024), 2)

    def test_missing_cache_dir(self, _isolate_cache_dir, monkeypatch):
        monkeypatch.setattr("backend.tts.cache.TTS_CACHE_DIR", "/nonexistent/path")
        result = cache_stats()
        assert result == {"files": 0, "bytes": 0, "mb": 0.0}


# ---------------------------------------------------------------------------
# evict_expired
# ---------------------------------------------------------------------------


class TestEvictExpired:
    def test_removes_old_files(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "old.wav", age_seconds=DEFAULT_TTL_SECONDS + 10)
        _write_file(_isolate_cache_dir, "conv1", "new.wav", age_seconds=100)

        removed = evict_expired()
        assert removed == 1

        conv_dir = _isolate_cache_dir / "conv1"
        assert not (conv_dir / "old.wav").exists()
        assert (conv_dir / "new.wav").exists()

    def test_nothing_to_remove(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "a.wav", age_seconds=10)
        removed = evict_expired()
        assert removed == 0

    def test_custom_ttl(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "mid.wav", age_seconds=500)
        removed = evict_expired(ttl_seconds=100)
        assert removed == 1

    def test_empty_cache_dir(self, _isolate_cache_dir):
        removed = evict_expired()
        assert removed == 0


# ---------------------------------------------------------------------------
# evict_lru
# ---------------------------------------------------------------------------


class TestEvictLru:
    def test_removes_oldest_until_under_budget(self, _isolate_cache_dir):
        # 3 files of 100 bytes each, budget = 150 bytes
        _write_file(_isolate_cache_dir, "conv1", "oldest.wav", b"x" * 100, age_seconds=300)
        _write_file(_isolate_cache_dir, "conv1", "mid.wav", b"x" * 100, age_seconds=200)
        _write_file(_isolate_cache_dir, "conv1", "newest.wav", b"x" * 100, age_seconds=10)

        removed = evict_lru(max_bytes=150)
        assert removed == 2  # oldest + mid removed
        assert (_isolate_cache_dir / "conv1" / "newest.wav").exists()

    def test_under_budget_no_removal(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "a.wav", b"x" * 10)
        removed = evict_lru(max_bytes=DEFAULT_MAX_CACHE_BYTES)
        assert removed == 0

    def test_empty_cache(self, _isolate_cache_dir):
        removed = evict_lru()
        assert removed == 0


# ---------------------------------------------------------------------------
# invalidate_cache_for_conversation
# ---------------------------------------------------------------------------


class TestInvalidateCacheForConversation:
    def test_removes_existing_conversation(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "a.wav")
        _write_file(_isolate_cache_dir, "conv2", "b.wav")

        result = invalidate_cache_for_conversation("conv1")
        assert result is True
        assert not (_isolate_cache_dir / "conv1").exists()
        assert (_isolate_cache_dir / "conv2").exists()

    def test_nonexistent_conversation(self, _isolate_cache_dir):
        result = invalidate_cache_for_conversation("nope")
        assert result is False


# ---------------------------------------------------------------------------
# run_eviction_cycle
# ---------------------------------------------------------------------------


class TestRunEvictionCycle:
    def test_returns_summary(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "a.wav", b"x" * 50)

        result = run_eviction_cycle()
        assert "ttl_removed" in result
        assert "lru_removed" in result
        assert "stats" in result
        assert result["stats"]["files"] == 1

    def test_ttl_then_lru(self, _isolate_cache_dir):
        # Old file (evicted by TTL)
        _write_file(
            _isolate_cache_dir,
            "conv1",
            "old.wav",
            b"x" * 100,
            age_seconds=DEFAULT_TTL_SECONDS + 10,
        )
        # New file within budget (kept)
        _write_file(_isolate_cache_dir, "conv1", "new.wav", b"x" * 50, age_seconds=10)

        result = run_eviction_cycle(max_bytes=DEFAULT_MAX_CACHE_BYTES)
        assert result["ttl_removed"] == 1
        assert result["lru_removed"] == 0
        assert result["stats"]["files"] == 1


# ---------------------------------------------------------------------------
# _prune_empty_dirs
# ---------------------------------------------------------------------------


class TestPruneEmptyDirs:
    def test_removes_empty_leaf_dirs(self, _isolate_cache_dir):
        (_isolate_cache_dir / "empty_conv").mkdir()
        _prune_empty_dirs()
        assert not (_isolate_cache_dir / "empty_conv").exists()

    def test_keeps_dirs_with_files(self, _isolate_cache_dir):
        _write_file(_isolate_cache_dir, "conv1", "a.wav")
        _prune_empty_dirs()
        assert (_isolate_cache_dir / "conv1").exists()

    def test_does_not_remove_cache_root(self, _isolate_cache_dir):
        _prune_empty_dirs()
        assert _isolate_cache_dir.exists()
