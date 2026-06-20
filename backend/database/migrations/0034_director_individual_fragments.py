"""Add the ``director_individual_fragments`` settings flag.

Fresh databases get the column from ``schema.py``; this backfills existing
ones. Default 0 keeps the director's single combined tool call.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "director_individual_fragments" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN director_individual_fragments INTEGER NOT NULL DEFAULT 0")
        print("[migrations] 0034: added director_individual_fragments column to settings")
