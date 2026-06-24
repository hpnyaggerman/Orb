"""
0031_anti_echo_audit_toggle -- add the `anti_echo` key to existing rows'
editor_audit_toggles so the Output Auditor's new anti-echo scanner persists as
enabled. New databases already get the key from the column default (schema.py);
this backfills databases created before the scanner existed.

run_audit's _on() already treats a missing key as enabled, so this is a
consistency backfill rather than a behavioural change — it just makes the
persisted JSON (and therefore the settings UI checkbox) reflect the default.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "editor_audit_toggles" not in cols:
        # Column itself is added by 0022; nothing to backfill if it's absent.
        return
    cur = conn.execute(
        "UPDATE settings "
        "SET editor_audit_toggles = json_set(editor_audit_toggles, '$.anti_echo', json('true')) "
        "WHERE json_extract(editor_audit_toggles, '$.anti_echo') IS NULL"
    )
    if cur.rowcount:
        print(f"[migrations] 0031: added anti_echo key to {cur.rowcount} settings row(s)")
