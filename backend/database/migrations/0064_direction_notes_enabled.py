"""Add the per-note ``enabled`` flag to ``direction_notes``."""

from __future__ import annotations

import sqlite3

# Databases that applied this migration under its former id still list that id,
# and the preset engine rejects any file whose ledger names a migration this build
# does not ship. Dropping the row here heals them when the migration re-runs under
# its current id; the column guard below makes that re-run a no-op.
_FORMER_ID = "0062_direction_notes_enabled"


def migrate(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'").fetchone():
        dropped = conn.execute("DELETE FROM schema_migrations WHERE id = ?", (_FORMER_ID,)).rowcount
        if dropped:
            print(f"[migrations] 0064: dropped the former ledger id {_FORMER_ID}")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(direction_notes)").fetchall()}
    if not cols or "enabled" in cols:
        return
    conn.execute("ALTER TABLE direction_notes ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
    print("[migrations] 0064: added enabled column to direction_notes")
