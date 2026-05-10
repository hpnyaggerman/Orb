"""Migration 0014: add progressive_fields to director_state, conversation_logs, and messages."""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    director_cols = {row[1] for row in conn.execute("PRAGMA table_info(director_state)").fetchall()}
    if "progressive_fields" not in director_cols:
        conn.execute("ALTER TABLE director_state ADD COLUMN progressive_fields TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
        print("[migrations] 0014: added progressive_fields column to director_state")

    log_cols = {row[1] for row in conn.execute("PRAGMA table_info(conversation_logs)").fetchall()}
    if "progressive_fields_after" not in log_cols:
        conn.execute("ALTER TABLE conversation_logs ADD COLUMN progressive_fields_after TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
        print("[migrations] 0014: added progressive_fields_after column to conversation_logs")

    message_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "progressive_fields" not in message_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN progressive_fields TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
        print("[migrations] 0014: added progressive_fields column to messages")
