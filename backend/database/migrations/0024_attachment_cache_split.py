"""
0024_attachment_cache_split -- split `message_attachments` into
`user_attachments` and `workflow_attachments`.

The split exists because the two row classes have diverged on lifecycle:
user uploads are authoritative bytes that must survive forever, while
workflow-produced bytes are a cache subject to LRU-3 eviction (sentinel
string "[evicted]" overwrites `data_b64` -- see
backend/secondary_workflows/attachment_cache.py:27 EVICTED_MARKER) and
carry sibling/parent lineage. Keeping them in one table forced the
storage layer to disambiguate provenance on every read.

Deliberate drop: any workflow-source rows already present in
`message_attachments` are discarded here, not copied. Workflow bytes
predating this migration were written without the lineage columns the
cache layer relies on; restoring them would create rows the cache could
not evict consistently.

The pre-0021 fork at the INSERT...SELECT (no `source` column case)
mirrors all surviving rows because, before 0021 added `source`, every
row was a user upload by definition.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    if "user_attachments" not in tables:
        conn.execute(
            """
            CREATE TABLE user_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                mime_type TEXT NOT NULL,
                data_b64 TEXT NOT NULL,
                filename TEXT,
                size INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )
        print("[migrations] 0024: created user_attachments")

    if "workflow_attachments" not in tables:
        conn.execute(
            """
            CREATE TABLE workflow_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                mime_type TEXT NOT NULL,
                data_b64 TEXT NOT NULL,
                filename TEXT,
                created_at TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                parent_attachment_id INTEGER REFERENCES workflow_attachments(id) ON DELETE CASCADE,
                annotation TEXT DEFAULT NULL,
                seed TEXT DEFAULT NULL,
                generation_metadata TEXT DEFAULT NULL,
                consumption_metadata TEXT DEFAULT NULL,
                active_sibling_id INTEGER REFERENCES workflow_attachments(id) ON DELETE SET NULL,
                recent_accesses TEXT DEFAULT NULL
            )
            """
        )
        print("[migrations] 0024: created workflow_attachments")

    if "message_attachments" in tables:
        ma_cols = {row[1] for row in conn.execute("PRAGMA table_info(message_attachments)").fetchall()}
        if "source" in ma_cols:
            conn.execute(
                """
                INSERT INTO user_attachments
                    (id, message_id, mime_type, data_b64, filename, size, created_at)
                SELECT id, message_id, mime_type, data_b64, filename, size, created_at
                FROM message_attachments
                WHERE (source = 'user' OR source IS NULL)
                  AND message_id IN (SELECT id FROM messages)
                """
            )
        else:
            conn.execute(
                """
                INSERT INTO user_attachments
                    (id, message_id, mime_type, data_b64, filename, size, created_at)
                SELECT id, message_id, mime_type, data_b64, filename, size, created_at
                FROM message_attachments
                WHERE message_id IN (SELECT id FROM messages)
                """
            )
        conn.execute("DROP TABLE message_attachments")
        print("[migrations] 0024: dropped message_attachments after user-row copy")

    settings_cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "attachment_cache_budget_bytes" not in settings_cols:
        conn.execute("ALTER TABLE settings ADD COLUMN attachment_cache_budget_bytes INTEGER NOT NULL DEFAULT 524288000")
        print("[migrations] 0024: added settings.attachment_cache_budget_bytes")
    if "attachment_access_counter" not in settings_cols:
        conn.execute("ALTER TABLE settings ADD COLUMN attachment_access_counter INTEGER NOT NULL DEFAULT 0")
        print("[migrations] 0024: added settings.attachment_access_counter")
