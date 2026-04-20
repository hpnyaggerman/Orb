"""
Integration test fixtures.

Strategy:
- Patch backend.database.DB_PATH to a per-test temp file before any DB call.
- Call init_db() directly (bypasses FastAPI lifespan, which ASGITransport does not trigger).
- Yield an httpx.AsyncClient wired to the real ASGI app.
- Yield a raw aiosqlite connection for direct DB assertions.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import httpx
import pytest
from httpx import ASGITransport

import backend.database as db_module
from backend.database import init_db


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
async def client(db_path: Path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))
    await init_db()

    from backend.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def db(db_path: Path):
    """Raw aiosqlite connection for post-call DB assertions."""
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn
