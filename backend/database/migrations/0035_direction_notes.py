"""Add the ``direction_notes`` table, its settings, and per-fragment recording timing.

Fresh installs get these from ``schema.py`` and ``SEED_INTERACTIVE_FRAGMENTS``; this
backfills existing ones, sourcing the table DDL from ``schema.py`` so the two shapes
cannot diverge. ``direction_notes_record`` defaults off, keeping recording opt-in;
``direction_notes_inject`` (``off``/``director``/``writer``/``both``) defaults to ``off``;
each direction-note fragment's ``direction_note_timing`` defaults to ``post_turn``, so it
records after the reply unless set to record before the writer.
"""

from __future__ import annotations

import sqlite3

from ..schema import table_create_sql


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(table_create_sql("direction_notes"))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dirnote_message ON direction_notes(message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dirnote_conversation ON direction_notes(conversation_id)")

    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "direction_notes_record" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN direction_notes_record INTEGER NOT NULL DEFAULT 0")
        print("[migrations] 0035: added direction_notes_record column to settings")
    if "direction_notes_inject" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN direction_notes_inject TEXT NOT NULL DEFAULT 'off'")
        print("[migrations] 0035: added direction_notes_inject column to settings")

    frag_cols = {row[1] for row in conn.execute("PRAGMA table_info(interactive_fragments)").fetchall()}
    if "direction_note_timing" not in frag_cols:
        conn.execute("ALTER TABLE interactive_fragments ADD COLUMN direction_note_timing TEXT NOT NULL DEFAULT 'post_turn'")
        print("[migrations] 0035: added direction_note_timing column to interactive_fragments")

    # Ship the default direction_note fragment to existing installs; the guard makes this a
    # no-op on fresh ones, which seeded it before migrations ran. The row is pinned here so a
    # later edit to the seed cannot change what an existing install received.
    frag_ids = {row[0] for row in conn.execute("SELECT id FROM interactive_fragments").fetchall()}
    if "story_direction" not in frag_ids:
        conn.execute(
            "INSERT INTO interactive_fragments "
            "(id, label, description, field_type, required, enabled, injection_label, sort_order, direction_note_timing) "
            "VALUES ('story_direction', 'Story Direction', ?, 'direction_note', 0, 0, 'Story direction', 6, 'post_turn')",
            (
                "Record a lasting development worth keeping for the rest of this branch: the direction of "
                "travel, an established fact, or a change to a character and the reason for it. Leave empty "
                "unless something genuinely new constrains future replies.",
            ),
        )
        print("[migrations] 0035: seeded the default 'story_direction' direction_note fragment")
