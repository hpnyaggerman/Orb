"""Turn model configs into named profiles that each own their endpoint row.

Fresh databases get both columns from ``schema.py`` and seed a single profile;
this backfills existing ones. A profile is one ``model_configs`` row plus its
``endpoints`` row, so editing its URL, key, API mode or proxy touches that
profile alone. Configs saved earlier could share one endpoint row; every config
past the one each row keeps moves to a copy of that row, and a lane (Writer or
Agent) that had the moved config selected follows it there, so each request
still reaches the same server with the same key and model.
"""

from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _split_shared_endpoints(conn: sqlite3.Connection) -> int:
    shared = [
        row[0]
        for row in conn.execute("SELECT endpoint_id FROM model_configs GROUP BY endpoint_id HAVING COUNT(*) > 1").fetchall()
    ]
    lanes = conn.execute("SELECT active_endpoint_id, agent_endpoint_id FROM settings WHERE id = 1").fetchone()
    writer_endpoint, agent_endpoint = lanes if lanes else (None, None)
    for endpoint_id in shared:
        url, api_key, completion_mode, proxy, writer_config, agent_config = conn.execute(
            "SELECT url, api_key, completion_mode, proxy, active_model_config_id, agent_active_model_config_id "
            "FROM endpoints WHERE id = ?",
            (endpoint_id,),
        ).fetchone()
        configs = [
            row[0] for row in conn.execute("SELECT id FROM model_configs WHERE endpoint_id = ? ORDER BY id", (endpoint_id,))
        ]
        keep = writer_config if writer_config in configs else agent_config if agent_config in configs else configs[0]
        for config_id in configs:
            if config_id == keep:
                continue
            copy_id = conn.execute(
                "INSERT INTO endpoints (url, api_key, completion_mode, proxy, active_model_config_id, agent_active_model_config_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (url, api_key, completion_mode, proxy, config_id, config_id),
            ).lastrowid
            conn.execute("UPDATE model_configs SET endpoint_id = ? WHERE id = ?", (copy_id, config_id))
            if writer_endpoint == endpoint_id and writer_config == config_id:
                conn.execute("UPDATE settings SET active_endpoint_id = ? WHERE id = 1", (copy_id,))
            if agent_endpoint == endpoint_id and agent_config == config_id:
                conn.execute("UPDATE settings SET agent_endpoint_id = ? WHERE id = 1", (copy_id,))
        # A pointer at a config that just moved would now name another row's
        # config; one that was empty or already pointed elsewhere is left as is.
        conn.execute(
            "UPDATE endpoints SET active_model_config_id = ?, agent_active_model_config_id = ? WHERE id = ?",
            (
                keep if writer_config in configs else writer_config,
                keep if agent_config in configs else agent_config,
                endpoint_id,
            ),
        )
    return len(shared)


def migrate(conn: sqlite3.Connection) -> None:
    config_cols = _columns(conn, "model_configs")
    fragment_cols = _columns(conn, "interactive_fragments")
    if not config_cols or not fragment_cols:
        return
    if "name" not in config_cols:
        conn.execute("ALTER TABLE model_configs ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        print("[migrations] 8003: added name column to model_configs")
    if "model_config_id" not in fragment_cols:
        conn.execute(
            "ALTER TABLE interactive_fragments ADD COLUMN model_config_id INTEGER REFERENCES model_configs(id) ON DELETE SET NULL"
        )
        print("[migrations] 8003: added model_config_id column to interactive_fragments")
    if split := _split_shared_endpoints(conn):
        print(f"[migrations] 8003: gave every model config on {split} shared endpoint(s) an endpoint of its own")
