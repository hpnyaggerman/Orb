"""
0013_agent_endpoint -- add separate agent endpoint/model configuration columns
for databases created before this feature existed.
"""

from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "agent_same_as_writer" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN agent_same_as_writer INTEGER NOT NULL DEFAULT 1")
        print("[migrations] 0013: added agent_same_as_writer column to settings")
    if "agent_endpoint_id" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN agent_endpoint_id INTEGER REFERENCES endpoints(id) ON DELETE SET NULL")
        print("[migrations] 0013: added agent_endpoint_id column to settings")
    if "agent_shared_system_prompt" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN agent_shared_system_prompt TEXT NOT NULL DEFAULT ''")
        print("[migrations] 0013: added agent_shared_system_prompt column to settings")

    ep_cols = {row[1] for row in conn.execute("PRAGMA table_info(endpoints)").fetchall()}
    if "agent_active_model_config_id" not in ep_cols:
        conn.execute(
            "ALTER TABLE endpoints ADD COLUMN agent_active_model_config_id INTEGER REFERENCES model_configs(id) ON DELETE SET NULL"
        )
        print("[migrations] 0013: added agent_active_model_config_id column to endpoints")
