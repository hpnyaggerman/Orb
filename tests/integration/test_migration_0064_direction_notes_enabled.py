"""Tests for migration 0064: the direction-notes ``enabled`` flag, and the ledger row a
database keeps when it applied the migration under its former id."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

from backend.database.migrations import MIGRATIONS, run_pending

_NAME = "0064_direction_notes_enabled"
_FORMER = "0062_direction_notes_enabled"

_NOTES_BEFORE = "CREATE TABLE direction_notes (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"
_NOTES_AFTER = (
    "CREATE TABLE direction_notes (id INTEGER PRIMARY KEY, content TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)"
)


def _migrate(conn: sqlite3.Connection) -> None:
    importlib.import_module(f"backend.database.migrations.{_NAME}").migrate(conn)


def _notes(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT enabled, content FROM direction_notes").fetchall()


def test_adds_the_flag_defaulting_on_and_reruns_as_a_no_op():
    conn = sqlite3.connect(":memory:")
    conn.execute(_NOTES_BEFORE)
    conn.execute("INSERT INTO direction_notes (content) VALUES ('kept')")
    _migrate(conn)
    assert _notes(conn) == [(1, "kept")]
    # No ledger table and the column already there: nothing to do, nothing raised.
    _migrate(conn)
    assert _notes(conn) == [(1, "kept")]


def test_a_database_that_applied_the_former_id_ends_with_a_ledger_this_build_recognizes(tmp_path: Path):
    """The preset engine rejects a file whose ledger names a migration the build does
    not ship, and snapshots clone the live ledger, so what matters is the ledger left
    behind: every id known, none stale."""
    db = tmp_path / "client.db"
    conn = sqlite3.connect(db)
    conn.execute(_NOTES_AFTER)
    conn.execute("INSERT INTO direction_notes (content) VALUES ('kept')")
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    applied_before = [name for name in MIGRATIONS if name != _NAME] + [_FORMER]
    conn.executemany("INSERT INTO schema_migrations (id) VALUES (?)", [(name,) for name in applied_before])
    conn.commit()
    conn.close()

    assert run_pending(db) == 1

    conn = sqlite3.connect(db)
    assert {row[0] for row in conn.execute("SELECT id FROM schema_migrations")} == set(MIGRATIONS)
    assert _notes(conn) == [(1, "kept")]
    conn.close()
