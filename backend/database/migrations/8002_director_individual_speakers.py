"""Add the ``director_individual_speakers`` settings flag.

Fresh databases get the column from ``schema.py``; this backfills existing
ones. Default 0 keeps one Director run per group exchange.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if not cols or "director_individual_speakers" in cols:
        return
    conn.execute("ALTER TABLE settings ADD COLUMN director_individual_speakers INTEGER NOT NULL DEFAULT 0")
    print("[migrations] 8002: added director_individual_speakers column to settings")
