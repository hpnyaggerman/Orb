"""
0021_workflow_attachments -- workflow-attachment columns on message_attachments.

Adds four columns:
  - source TEXT NOT NULL DEFAULT 'user' -- provenance label
  - workflow_id TEXT DEFAULT NULL       -- producing workflow id when source != 'user'
  - parent_attachment_id INTEGER DEFAULT NULL -- regen lineage; NULL on root rows
  - annotation TEXT DEFAULT NULL        -- LLM-visible history text for root rows

Inert at this migration boundary -- existing rows default source='user',
others NULL, preserving current behavior.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(message_attachments)").fetchall()}
    if "source" not in cols:
        conn.execute("ALTER TABLE message_attachments ADD COLUMN source TEXT NOT NULL DEFAULT 'user'")
        print("[migrations] 0021: added source column to message_attachments")
    if "workflow_id" not in cols:
        conn.execute("ALTER TABLE message_attachments ADD COLUMN workflow_id TEXT DEFAULT NULL")
        print("[migrations] 0021: added workflow_id column to message_attachments")
    if "parent_attachment_id" not in cols:
        conn.execute("ALTER TABLE message_attachments ADD COLUMN parent_attachment_id INTEGER DEFAULT NULL")
        print("[migrations] 0021: added parent_attachment_id column to message_attachments")
    if "annotation" not in cols:
        conn.execute("ALTER TABLE message_attachments ADD COLUMN annotation TEXT DEFAULT NULL")
        print("[migrations] 0021: added annotation column to message_attachments")
