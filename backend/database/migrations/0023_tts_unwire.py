"""
0023_tts_unwire -- port TTS data into settings.workflow_config["tts"], drop legacy
table + columns.

Reads voice_profiles rows + settings.tts_* columns into settings.workflow_config["tts"],
then drops the legacy storage. Idempotent: re-running with both source paths absent
short-circuits without overwriting an already-populated workflow_config["tts"] slot.
"""

from __future__ import annotations

import json
import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    settings_cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    has_tts_cols = any(c in settings_cols for c in ("tts_enabled", "tts_auto_speak", "tts_volume"))
    has_voice_table = "voice_profiles" in tables

    if not has_tts_cols and not has_voice_table:
        print("[migrations] 0023: no TTS sources present; nothing to port or drop")
        return

    tts_settings: dict = {}
    if "tts_enabled" in settings_cols:
        tts_settings["tts_enabled"] = "tts_enabled"
    if "tts_auto_speak" in settings_cols:
        tts_settings["tts_auto_speak"] = "tts_auto_speak"
    if "tts_volume" in settings_cols:
        tts_settings["tts_volume"] = "tts_volume"

    select_cols = ["workflow_config"] + list(tts_settings.values())
    row = conn.execute(f"SELECT {', '.join(select_cols)} FROM settings WHERE id = 1").fetchone()

    if row is None:
        print("[migrations] 0023: no settings row; skipping data port")
    else:
        try:
            workflow_config = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            workflow_config = {}

        tts_slot: dict = {
            "enabled": False,
            "auto_speak": False,
            "volume": 0.75,
            "per_character": {},
        }
        for idx, key in enumerate(tts_settings.keys(), start=1):
            value = row[idx]
            if key == "tts_enabled":
                tts_slot["enabled"] = bool(value)
            elif key == "tts_auto_speak":
                tts_slot["auto_speak"] = bool(value)
            elif key == "tts_volume" and value is not None:
                tts_slot["volume"] = float(value)

        if has_voice_table:
            for vp in conn.execute(
                """
                SELECT character_card_id, backend, voice_id, language, rate, pitch,
                       enabled, endpoint_id, api_url, api_key, model
                FROM voice_profiles
                """
            ).fetchall():
                card_id = vp[0]
                tts_slot["per_character"][card_id] = {
                    "backend": vp[1],
                    "voice_id": vp[2],
                    "language": vp[3],
                    "rate": vp[4],
                    "pitch": vp[5],
                    "enabled": bool(vp[6]),
                    "endpoint_id": vp[7],
                    "api_url": vp[8] or "",
                    "api_key": vp[9] or "",
                    "model": vp[10] or "",
                }

        workflow_config["tts"] = tts_slot
        conn.execute(
            "UPDATE settings SET workflow_config = ? WHERE id = 1",
            (json.dumps(workflow_config),),
        )
        conn.commit()
        print(
            f"[migrations] 0023: ported TTS into workflow_config " f"(per_character entries: {len(tts_slot['per_character'])})"
        )

    if "tts_enabled" in settings_cols:
        conn.execute("ALTER TABLE settings DROP COLUMN tts_enabled")
        conn.commit()
        print("[migrations] 0023: dropped settings.tts_enabled")
    if "tts_auto_speak" in settings_cols:
        conn.execute("ALTER TABLE settings DROP COLUMN tts_auto_speak")
        conn.commit()
        print("[migrations] 0023: dropped settings.tts_auto_speak")
    if "tts_volume" in settings_cols:
        conn.execute("ALTER TABLE settings DROP COLUMN tts_volume")
        conn.commit()
        print("[migrations] 0023: dropped settings.tts_volume")

    if has_voice_table:
        conn.execute("DROP TABLE voice_profiles")
        conn.commit()
        print("[migrations] 0023: dropped voice_profiles table")
