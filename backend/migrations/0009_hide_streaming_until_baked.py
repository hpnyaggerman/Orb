"""
0008_hide_streaming_until_baked -- add hide_streaming_until_baked column to
settings table for databases created before this toggle existed.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()]

    if "hide_streaming_until_baked" not in columns:
        conn.execute(
            "ALTER TABLE settings ADD COLUMN hide_streaming_until_baked INTEGER NOT NULL DEFAULT 0"
        )
        print("[migrations] 0008: added hide_streaming_until_baked column to settings")
