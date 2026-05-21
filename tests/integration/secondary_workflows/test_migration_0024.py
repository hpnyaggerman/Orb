"""Tests for migration 0024_attachment_cache_split.

Uses sqlite3 directly to stage pre-migration DB states (post-0021,
pre-0024) that the production init_db + run_pending flow does not
produce. The migration runner is synchronous and takes a connection,
so bypassing aiosqlite + the FastAPI app is the cheapest fit.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest

import backend.database.connection as db_connection
from backend.database.migrations import run_pending


def _import_migration(name: str):
    return importlib.import_module(f"backend.database.migrations.{name}")


@pytest.fixture
def mig_db(tmp_path: Path, monkeypatch):
    path = tmp_path / "mig.db"
    monkeypatch.setattr(db_connection, "DB_PATH", str(path))
    return path


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _bootstrap_with_post0024_schema(mig_db: Path) -> None:
    """Mirror the production flow up to and including the seed step for
    director_fragments (which migration 0005 looks at), then mark all
    pre-0024 migrations as already applied so run_pending only fires
    migration 0024."""
    from backend.database.schema import CREATE_TABLES_SQL
    from backend.database.migrations import MIGRATIONS

    conn = sqlite3.connect(str(mig_db))
    try:
        conn.executescript(CREATE_TABLES_SQL)
        # Seed the one fragment 0005 checks for; we are not exercising 0005 here.
        conn.execute(
            "INSERT INTO director_fragments (id, label, description, field_type, required, enabled, injection_label, sort_order) "
            "VALUES ('keywords', 'Keywords', 'desc', 'array', 1, 1, 'Keywords', 2)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        for name in MIGRATIONS:
            if name < "0024":
                conn.execute("INSERT OR IGNORE INTO schema_migrations (id) VALUES (?)", (name,))
        conn.commit()
    finally:
        conn.close()


def test_run_pending_on_fresh_db_creates_split_tables(mig_db: Path):
    _bootstrap_with_post0024_schema(mig_db)
    run_pending(mig_db)

    conn = sqlite3.connect(str(mig_db))
    try:
        tables = _table_names(conn)
        assert "user_attachments" in tables
        assert "workflow_attachments" in tables
        assert "message_attachments" not in tables
    finally:
        conn.close()


def test_workflow_attachments_has_expected_columns(mig_db: Path):
    _bootstrap_with_post0024_schema(mig_db)
    run_pending(mig_db)

    conn = sqlite3.connect(str(mig_db))
    try:
        cols = _columns(conn, "workflow_attachments")
        assert {
            "id",
            "message_id",
            "mime_type",
            "data_b64",
            "filename",
            "created_at",
            "workflow_id",
            "parent_attachment_id",
            "annotation",
            "seed",
            "generation_metadata",
            "active_sibling_id",
            "recent_accesses",
        }.issubset(cols)
        assert "size" not in cols, "size column removed: byte count derives from data_b64"
    finally:
        conn.close()


def test_settings_has_cache_columns_after_migration(mig_db: Path):
    _bootstrap_with_post0024_schema(mig_db)
    run_pending(mig_db)

    conn = sqlite3.connect(str(mig_db))
    try:
        cols = _columns(conn, "settings")
        assert "attachment_cache_budget_bytes" in cols
        assert "attachment_access_counter" in cols
    finally:
        conn.close()


def _seed_pre_0024(conn: sqlite3.Connection) -> None:
    """Stage a post-0021, pre-0024 DB shape so run_pending() fires only
    migration 0024. Seeds rows on both sides of source='user' vs
    source='workflow:wf' so the copy/drop split in 0024 can be exercised."""
    conn.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created_at TEXT NOT NULL, updated_at TEXT, active_leaf_id INTEGER)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, turn_index INTEGER NOT NULL, parent_id INTEGER, progressive_fields TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE message_attachments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "message_id INTEGER NOT NULL, "
        "mime_type TEXT NOT NULL, "
        "data_b64 TEXT NOT NULL, "
        "filename TEXT, "
        "size INTEGER, "
        "created_at TEXT NOT NULL, "
        "source TEXT NOT NULL DEFAULT 'user', "
        "workflow_id TEXT, "
        "parent_attachment_id INTEGER, "
        "annotation TEXT)"
    )
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), endpoint_url TEXT NOT NULL DEFAULT '', model_name TEXT NOT NULL DEFAULT '')"
    )
    conn.execute("INSERT INTO settings (id, endpoint_url, model_name) VALUES (1, '', '')")
    conn.execute("INSERT INTO conversations (id, title, created_at) VALUES ('c1', 't', '2026-05-15T00:00:00Z')")
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, turn_index, created_at) "
        "VALUES (1, 'c1', 'assistant', 'x', 0, '2026-05-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO message_attachments (id, message_id, mime_type, data_b64, filename, size, created_at, source) "
        "VALUES (10, 1, 'image/png', 'VVA==', 'u.png', 4, '2026-05-15T00:00:00Z', 'user')"
    )
    conn.execute(
        "INSERT INTO message_attachments (id, message_id, mime_type, data_b64, filename, size, created_at, source, workflow_id) "
        "VALUES (11, 1, 'image/png', 'V0Y=', 'wf.png', 3, '2026-05-15T00:00:00Z', 'workflow:wf', 'wf')"
    )
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    from backend.database.migrations import MIGRATIONS

    for name in MIGRATIONS:
        if name < "0024":
            conn.execute("INSERT INTO schema_migrations (id) VALUES (?)", (name,))
    conn.commit()


def test_upgrade_copies_user_rows_and_drops_workflow_rows(mig_db: Path):
    conn = sqlite3.connect(str(mig_db))
    try:
        _seed_pre_0024(conn)
    finally:
        conn.close()

    run_pending(mig_db)

    conn = sqlite3.connect(str(mig_db))
    try:
        tables = _table_names(conn)
        assert "message_attachments" not in tables
        rows = conn.execute("SELECT id, mime_type, filename, size FROM user_attachments").fetchall()
        assert rows == [(10, "image/png", "u.png", 4)]
        wf_rows = conn.execute("SELECT COUNT(*) FROM workflow_attachments").fetchone()
        assert wf_rows[0] == 0, "workflow rows discarded on upgrade (branch unmerged)"
    finally:
        conn.close()


def test_migration_0024_running_twice_is_a_noop(mig_db: Path):
    from backend.database.schema import CREATE_TABLES_SQL

    conn = sqlite3.connect(str(mig_db))
    try:
        conn.executescript(CREATE_TABLES_SQL)
        conn.commit()
    finally:
        conn.close()

    mod = _import_migration("0024_attachment_cache_split")
    conn = sqlite3.connect(str(mig_db))
    try:
        mod.migrate(conn)
        mod.migrate(conn)  # second pass must not raise
        conn.commit()
    finally:
        conn.close()
