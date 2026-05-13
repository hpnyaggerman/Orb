"""
0020_workflow_storage -- per-workflow JSON storage columns.

Adds two JSON columns:
  - conversations.workflow_state TEXT DEFAULT NULL
  - settings.workflow_config TEXT NOT NULL DEFAULT '{}'

Both columns hold opaque JSON shaped as {<workflow_id>: <dict>, ...}, with each
workflow owning its own slot. The columns are inert at this migration boundary
-- no reader exists yet.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    conv_cols = {row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "workflow_state" not in conv_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN workflow_state TEXT DEFAULT NULL")
        print("[migrations] 0020: added workflow_state column to conversations")

    settings_cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "workflow_config" not in settings_cols:
        conn.execute("ALTER TABLE settings ADD COLUMN workflow_config TEXT NOT NULL DEFAULT '{}'")
        print("[migrations] 0020: added workflow_config column to settings")
