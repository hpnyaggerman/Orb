from __future__ import annotations

from typing import cast

from ..connection import _build_set_clause, get_db
from ..models import EndpointRow, ModelConfigRow, ProfileRow

# The EndpointRow projection. Spelled once so every read of the table returns the
# same columns — `SELECT *` would leak future columns into the row contract.
_ENDPOINT_COLS = "id, url, api_key, active_model_config_id, agent_active_model_config_id, completion_mode, proxy"

_PROFILE_SELECT = (
    "SELECT mc.*, e.url AS endpoint_url, e.api_key, e.completion_mode, e.proxy "
    "FROM model_configs mc JOIN endpoints e ON mc.endpoint_id = e.id"
)


async def _endpoint_on(db, endpoint_id: int) -> EndpointRow | None:
    """Read one endpoint over an open connection; None when it does not exist."""
    rows = list(await db.execute_fetchall(f"SELECT {_ENDPOINT_COLS} FROM endpoints WHERE id = ?", (endpoint_id,)))  # nosec B608
    return cast(EndpointRow, dict(rows[0])) if rows else None


async def get_endpoints() -> list[EndpointRow]:
    async with get_db() as db:
        rows = list(await db.execute_fetchall(f"SELECT {_ENDPOINT_COLS} FROM endpoints ORDER BY id ASC"))  # nosec B608
        return [cast(EndpointRow, dict(r)) for r in rows]


async def get_endpoint(endpoint_id: int) -> EndpointRow | None:
    async with get_db() as db:
        return await _endpoint_on(db, endpoint_id)


async def create_endpoint(url: str, api_key: str = "") -> EndpointRow:
    async with get_db() as db:
        cur = await db.execute("INSERT INTO endpoints (url, api_key) VALUES (?, ?)", (url, api_key))
        assert cur.lastrowid is not None
        endpoint_id = cur.lastrowid
        cur_w = await db.execute(
            "INSERT INTO model_configs (endpoint_id, model_name, system_prompt, temperature, min_p, top_k, top_p, repetition_penalty, max_tokens, role) VALUES (?, 'default', '', 0.8, 0.0, 40, 0.95, 1.0, 4096, 'writer')",
            (endpoint_id,),
        )
        cur_a = await db.execute(
            "INSERT INTO model_configs (endpoint_id, model_name, system_prompt, temperature, min_p, top_k, top_p, repetition_penalty, max_tokens, role) VALUES (?, 'default', '', 0.8, 0.0, 40, 0.95, 1.0, 4096, 'agent')",
            (endpoint_id,),
        )
        await db.execute(
            "UPDATE endpoints SET active_model_config_id = ?, agent_active_model_config_id = ? WHERE id = ?",
            (cur_w.lastrowid, cur_a.lastrowid, endpoint_id),
        )
        await db.commit()
        created = await _endpoint_on(db, endpoint_id)
        assert created is not None
        return created


async def update_endpoint(endpoint_id: int, data: dict) -> EndpointRow | None:
    async with get_db() as db:
        allowed = [
            "url",
            "api_key",
            "active_model_config_id",
            "agent_active_model_config_id",
            "completion_mode",
            "proxy",
        ]
        sets, vals = _build_set_clause(allowed, data)
        if sets:
            vals.append(endpoint_id)
            await db.execute(
                f"UPDATE endpoints SET {', '.join(sets)} WHERE id = ?",  # nosec B608
                vals,
            )
            await db.commit()
        return await _endpoint_on(db, endpoint_id)


async def delete_endpoint(endpoint_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute("DELETE FROM endpoints WHERE id = ?", (endpoint_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_model_configs(endpoint_id: int) -> list[ModelConfigRow]:
    async with get_db() as db:
        rows = list(
            await db.execute_fetchall(
                "SELECT * FROM model_configs WHERE endpoint_id = ? ORDER BY id ASC",
                (endpoint_id,),
            )
        )
        return [cast(ModelConfigRow, dict(r)) for r in rows]


async def create_model_config(endpoint_id: int, data: dict) -> ModelConfigRow:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO model_configs (endpoint_id, model_name, system_prompt, temperature, min_p, top_k, top_p, repetition_penalty, max_tokens, role, reasoning_effort, reasoning_effort_param, reasoning_effort_value, extra_headers, extra_body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                endpoint_id,
                data.get("model_name", "default"),
                data.get("system_prompt", ""),
                data.get("temperature", 0.8),
                data.get("min_p", 0.0),
                data.get("top_k", 40),
                data.get("top_p", 0.95),
                data.get("repetition_penalty", 1.0),
                data.get("max_tokens", 4096),
                data.get("role", "writer"),
                data.get("reasoning_effort", ""),
                data.get("reasoning_effort_param", ""),
                data.get("reasoning_effort_value", ""),
                data.get("extra_headers", ""),
                data.get("extra_body", ""),
            ),
        )
        await db.commit()
        rows = list(await db.execute_fetchall("SELECT * FROM model_configs WHERE id = ?", (cur.lastrowid,)))
        return cast(ModelConfigRow, dict(rows[0]))


async def update_model_config(config_id: int, data: dict) -> ModelConfigRow | None:
    async with get_db() as db:
        allowed = [
            "name",
            "model_name",
            "system_prompt",
            "temperature",
            "min_p",
            "top_k",
            "top_p",
            "repetition_penalty",
            "max_tokens",
            "reasoning_effort",
            "reasoning_effort_param",
            "reasoning_effort_value",
            "extra_headers",
            "extra_body",
        ]
        sets, vals = _build_set_clause(allowed, data)
        if sets:
            vals.append(config_id)
            await db.execute(
                f"UPDATE model_configs SET {', '.join(sets)} WHERE id = ?",  # nosec B608
                vals,
            )
            await db.commit()
        rows = list(await db.execute_fetchall("SELECT * FROM model_configs WHERE id = ?", (config_id,)))
        return cast(ModelConfigRow, dict(rows[0])) if rows else None


async def delete_model_config(config_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute("DELETE FROM model_configs WHERE id = ?", (config_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_profiles() -> list[ProfileRow]:
    async with get_db() as db:
        rows = list(await db.execute_fetchall(f"{_PROFILE_SELECT} ORDER BY mc.id ASC"))  # nosec B608
        return [cast(ProfileRow, dict(r)) for r in rows]


async def create_profile(data: dict) -> ProfileRow:
    """Insert a profile's endpoint row and model config together, both lane pointers on it."""
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO endpoints (url, api_key, completion_mode, proxy) VALUES (?, ?, ?, ?)",
            (data["endpoint_url"], data.get("api_key", ""), data.get("completion_mode", "chat"), data.get("proxy", "")),
        )
        endpoint_id = cur.lastrowid
        cur = await db.execute(
            "INSERT INTO model_configs (endpoint_id, name, model_name, system_prompt, temperature, min_p, top_k, top_p, repetition_penalty, max_tokens, role, reasoning_effort, reasoning_effort_param, reasoning_effort_value, extra_headers, extra_body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                endpoint_id,
                data["name"],
                data.get("model_name", "default"),
                data.get("system_prompt", ""),
                data.get("temperature", 0.8),
                data.get("min_p", 0.0),
                data.get("top_k", 40),
                data.get("top_p", 0.95),
                data.get("repetition_penalty", 1.0),
                data.get("max_tokens", 4096),
                data.get("role", "writer"),
                data.get("reasoning_effort", ""),
                data.get("reasoning_effort_param", ""),
                data.get("reasoning_effort_value", ""),
                data.get("extra_headers", ""),
                data.get("extra_body", ""),
            ),
        )
        config_id = cur.lastrowid
        await db.execute(
            "UPDATE endpoints SET active_model_config_id = ?, agent_active_model_config_id = ? WHERE id = ?",
            (config_id, config_id, endpoint_id),
        )
        await db.commit()
        rows = list(await db.execute_fetchall(f"{_PROFILE_SELECT} WHERE mc.id = ?", (config_id,)))  # nosec B608
        return cast(ProfileRow, dict(rows[0]))


async def delete_profile(config_id: int) -> bool:
    """Delete a profile's model config, and its endpoint row once no other config uses it."""
    async with get_db() as db:
        rows = list(await db.execute_fetchall("SELECT endpoint_id FROM model_configs WHERE id = ?", (config_id,)))
        if not rows:
            return False
        endpoint_id = rows[0]["endpoint_id"]
        await db.execute("DELETE FROM model_configs WHERE id = ?", (config_id,))
        await db.execute(
            "DELETE FROM endpoints WHERE id = ? AND NOT EXISTS (SELECT 1 FROM model_configs WHERE endpoint_id = ?)",
            (endpoint_id, endpoint_id),
        )
        await db.commit()
        return True
