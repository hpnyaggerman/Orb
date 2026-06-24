"""
0032_conversation_last_accessed — add last_accessed_at to conversations.

Splits the side-panel ordering signal away from updated_at: updated_at now
means only "content changed" (new/regenerated message), while last_accessed_at
tracks when a conversation was opened/selected. Backfilled from updated_at so
existing ordering is unchanged on first run.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()]
    if "last_accessed_at" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN last_accessed_at TEXT")
        conn.execute("UPDATE conversations SET last_accessed_at = updated_at")
        print("[migrations] 0032: added last_accessed_at column to conversations")
