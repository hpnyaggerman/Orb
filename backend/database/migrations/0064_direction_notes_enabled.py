"""Add the per-note ``enabled`` flag to ``direction_notes``."""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(direction_notes)").fetchall()}
    if not cols or "enabled" in cols:
        return
    conn.execute("ALTER TABLE direction_notes ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
    print("[migrations] 0064: added enabled column to direction_notes")
