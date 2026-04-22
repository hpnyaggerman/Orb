"""
0010_add_show_editor_diff -- add show_editor_diff column to settings table for
databases created before this toggle existed.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()]

    if "show_editor_diff" not in columns:
        conn.execute(
            "ALTER TABLE settings ADD COLUMN show_editor_diff INTEGER NOT NULL DEFAULT 1"
        )
        print("[migrations] 0010: added show_editor_diff column to settings")
