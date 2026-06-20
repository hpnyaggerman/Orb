"""Add the ``direction_notes`` table, its settings, and the default fragment.

Fresh databases get the table/settings from ``schema.py`` and the default fragment
from ``SEED_INTERACTIVE_FRAGMENTS``; this backfills existing ones. The table DDL is
sourced from ``schema.py`` so the backfilled shape cannot drift from the fresh-install
shape. ``direction_notes_mode`` default ``'off'`` keeps recording disabled until opted
in; ``direction_notes_inject`` default ``1`` injects stored notes by default once
recording produces any; ``direction_notes_recipient`` default ``'both'`` feeds them to
the director and writer.
"""

from __future__ import annotations

import sqlite3

from ..schema import table_create_sql


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(table_create_sql("direction_notes"))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dirnote_message ON direction_notes(message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dirnote_conversation ON direction_notes(conversation_id)")

    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "direction_notes_mode" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN direction_notes_mode TEXT NOT NULL DEFAULT 'off'")
        print("[migrations] 0035: added direction_notes_mode column to settings")
    if "direction_notes_inject" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN direction_notes_inject INTEGER NOT NULL DEFAULT 1")
        print("[migrations] 0035: added direction_notes_inject column to settings")
    if "direction_notes_recipient" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN direction_notes_recipient TEXT NOT NULL DEFAULT 'both'")
        print("[migrations] 0035: added direction_notes_recipient column to settings")

    # Ship the default direction_note fragment to existing installs. Fresh installs get
    # it from SEED_INTERACTIVE_FRAGMENTS, which runs before migrations, so the guard makes
    # this a no-op there. Frozen copy of that seed entry (migrations must not drift with
    # later seed edits); keep the two in sync when changing the default.
    frag_ids = {row[0] for row in conn.execute("SELECT id FROM interactive_fragments").fetchall()}
    if "story_direction" not in frag_ids:
        conn.execute(
            "INSERT INTO interactive_fragments "
            "(id, label, description, field_type, required, enabled, injection_label, sort_order) "
            "VALUES ('story_direction', 'Story Direction', ?, 'direction_note', 0, 0, 'Story direction', 6)",
            (
                "Record a lasting development worth keeping for the rest of this branch: the direction of "
                "travel, an established fact, or a change to a character and the reason for it. Leave empty "
                "unless something genuinely new constrains future replies.",
            ),
        )
        print("[migrations] 0035: seeded the default 'story_direction' direction_note fragment")
