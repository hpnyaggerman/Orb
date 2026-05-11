"""
0019_lorebook_constant -- add `constant` column to lorebook_entries.

When set, the entry is always injected regardless of keyword matches.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(lorebook_entries)").fetchall()}
    if "constant" not in cols:
        conn.execute("ALTER TABLE lorebook_entries ADD COLUMN constant BOOLEAN NOT NULL DEFAULT 0")
        print("[migrations] 0019: added constant column to lorebook_entries")
