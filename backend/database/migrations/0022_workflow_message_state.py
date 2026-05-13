"""
0022_workflow_message_state -- per-message workflow state column.

Adds messages.workflow_state TEXT DEFAULT NULL, an opaque JSON blob shaped as
{<workflow_id>: <dict>, ...} for per-message workflow caches (per-message
emotion, per-message facts, etc.). Same column name as the per-conversation
sibling on conversations; scope is distinguished by table.

Lifecycle matches the message row -- deleting the message drops the column
value automatically.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "workflow_state" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN workflow_state TEXT DEFAULT NULL")
        print("[migrations] 0022: added workflow_state column to messages")
