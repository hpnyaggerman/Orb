"""Add the ``llm_proxy`` settings column.

Fresh installs get the column from ``schema.py``; this backfills existing ones.
Empty string means no proxy, so LLM chat-completion requests keep connecting
directly (the prior behavior) until a proxy URL is set in Settings.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "llm_proxy" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN llm_proxy TEXT NOT NULL DEFAULT ''")
        print("[migrations] 0036: added llm_proxy column to settings")
