"""Endpoint profiles: a model config plus an endpoint row of its own, picked per lane
and, under individual fragment processing, per Director fragment.

Covers the profile routes (list, create, rename, delete), the fragment override's
write path, where each Director call is sent once fragments carry overrides, and
migration 8003, which gives every config that shared an endpoint row one of its
own without moving any lane off the server, key, and model it used before.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import backend.database as dbmod
import backend.database.connection as db_connection
from backend.database.queries.settings import get_settings
from backend.pipeline import handle_turn
from backend.prompting.tool_schemas import wire_field

_FRAGMENT_URL = "http://fragment.local/v1"
_FRAGMENT_PRESET = {"temperature": 0.1, "top_k": 7, "min_p": 0.3, "max_tokens": 321}


async def _drain(agen) -> list[dict]:
    return [ev async for ev in agen]


async def _create_profile(client, name: str = "Fragment model", **fields) -> dict:
    body = {"name": name, "endpoint_url": _FRAGMENT_URL, "api_key": "frag-key", "model_name": "frag-model", **fields}
    resp = await client.post("/api/profiles", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _endpoint(db, endpoint_id: int) -> dict | None:
    async with db.execute("SELECT * FROM endpoints WHERE id = ?", (endpoint_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def _fragment(fid: str, field_type: str = "string", *, label: str = "", model_config_id: int | None = None) -> None:
    await dbmod.create_interactive_fragment(
        {
            "id": fid,
            "label": label or fid.title(),
            "description": f"Decide the {fid}.",
            "field_type": field_type,
            "injection_label": label or fid.title(),
            "model_config_id": model_config_id,
        }
    )


# -- routes ------------------------------------------------------------------


async def test_a_fresh_install_seeds_one_profile_with_an_endpoint_of_its_own(client, db):
    profiles = (await client.get("/api/profiles")).json()
    assert len(profiles) == 1
    seeded = profiles[0]
    endpoint = await _endpoint(db, seeded["endpoint_id"])
    assert endpoint is not None
    assert endpoint["active_model_config_id"] == endpoint["agent_active_model_config_id"] == seeded["id"]
    assert (await client.get("/api/settings")).json()["active_endpoint_id"] == seeded["endpoint_id"]


async def test_a_created_profile_owns_its_endpoint(client, db):
    seeded = (await client.get("/api/profiles")).json()[0]
    profile = await _create_profile(client, completion_mode="text", proxy="socks5://127.0.0.1:1080", **_FRAGMENT_PRESET)

    assert profile["name"] == "Fragment model"
    assert profile["endpoint_url"] == _FRAGMENT_URL
    assert profile["api_key"] == "frag-key"
    assert profile["completion_mode"] == "text"
    assert profile["proxy"] == "socks5://127.0.0.1:1080"
    assert {k: profile[k] for k in _FRAGMENT_PRESET} == _FRAGMENT_PRESET
    assert profile["endpoint_id"] != seeded["endpoint_id"]
    endpoint = await _endpoint(db, profile["endpoint_id"])
    assert endpoint is not None
    assert endpoint["active_model_config_id"] == endpoint["agent_active_model_config_id"] == profile["id"]

    # Editing one profile's connection leaves every other profile's alone.
    await client.put(f"/api/endpoints/{profile['endpoint_id']}", json={"url": "http://moved.local/v1", "api_key": "k2"})
    by_id = {p["id"]: p for p in (await client.get("/api/profiles")).json()}
    assert by_id[profile["id"]]["endpoint_url"] == "http://moved.local/v1"
    assert by_id[seeded["id"]]["endpoint_url"] == seeded["endpoint_url"]
    assert by_id[seeded["id"]]["api_key"] == seeded["api_key"]


async def test_a_profile_needs_a_name_and_a_valid_proxy(client):
    for body in (
        {"name": "  ", "endpoint_url": _FRAGMENT_URL, "model_name": "m"},
        {"name": "P", "endpoint_url": _FRAGMENT_URL, "model_name": "m", "proxy": "ftp://nope"},
        {"name": "P", "endpoint_url": _FRAGMENT_URL, "model_name": "m", "extra_body": "[1]"},
    ):
        assert (await client.post("/api/profiles", json=body)).status_code == 422
    assert len((await client.get("/api/profiles")).json()) == 1


async def test_a_profile_is_renamed_through_its_model_config(client):
    profile = await _create_profile(client)
    resp = await client.put(f"/api/models/{profile['id']}", json={"name": "Director scout"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Director scout"
    assert {p["id"]: p["name"] for p in (await client.get("/api/profiles")).json()}[profile["id"]] == "Director scout"


async def test_deleting_a_profile_removes_its_endpoint_and_every_reference(client, db):
    profile = await _create_profile(client)
    await client.put("/api/settings", json={"agent_same_as_writer": False, "agent_endpoint_id": profile["endpoint_id"]})
    await _fragment("pace", model_config_id=profile["id"])

    assert (await client.delete(f"/api/profiles/{profile['id']}")).status_code == 200

    assert profile["id"] not in {p["id"] for p in (await client.get("/api/profiles")).json()}
    assert await _endpoint(db, profile["endpoint_id"]) is None
    assert (await client.get("/api/settings")).json()["agent_endpoint_id"] is None
    fragment = await dbmod.get_interactive_fragment("pace")
    assert fragment is not None and fragment.get("model_config_id") is None
    assert (await client.delete(f"/api/profiles/{profile['id']}")).status_code == 404


async def test_deleting_a_profile_keeps_an_endpoint_another_config_still_uses(client, db):
    # The legacy route still provisions two configs on one endpoint row.
    endpoint_id = (await client.post("/api/endpoints", json={"url": "http://legacy.local", "api_key": "k"})).json()["id"]
    first, second = (await client.get(f"/api/endpoints/{endpoint_id}/models")).json()

    assert (await client.delete(f"/api/profiles/{first['id']}")).status_code == 200

    assert await _endpoint(db, endpoint_id) is not None
    assert [m["id"] for m in (await client.get(f"/api/endpoints/{endpoint_id}/models")).json()] == [second["id"]]


async def test_a_fragment_override_is_set_kept_and_cleared(client):
    profile = await _create_profile(client)
    base = {"id": "pace", "label": "Pace", "description": "d", "injection_label": "Pace"}
    created = await client.post("/api/interactive-fragments", json={**base, "model_config_id": profile["id"]})
    assert created.status_code == 200
    assert created.json()["model_config_id"] == profile["id"]

    # A partial update that does not name the override leaves it alone.
    toggled = await client.put("/api/interactive-fragments/pace", json={"enabled": False})
    assert toggled.json()["model_config_id"] == profile["id"]

    cleared = await client.put("/api/interactive-fragments/pace", json={"model_config_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["model_config_id"] is None

    missing = await client.put("/api/interactive-fragments/pace", json={"model_config_id": 999_999})
    assert missing.status_code == 404
    unknown = await client.post("/api/interactive-fragments", json={**base, "id": "other", "model_config_id": 999_999})
    assert unknown.status_code == 404


# -- routing -----------------------------------------------------------------


def _director_call(llm_mock, fid: str) -> dict:
    wire = wire_field(fid)
    return next(
        c
        for c in llm_mock.captured
        if c["pass"] == "director" and wire in ((c["params"].get("json_schema") or {}).get("properties") or {})
    )


async def _individual_turn(client, llm_mock, cid: str, *, individual: bool = True, **settings) -> None:
    await dbmod.create_conversation(cid, "profiles", "Bot", "a scenario")
    await client.put(
        "/api/settings",
        json={
            "enable_agent": True,
            "enabled_tools": {"direct_scene": True},
            "director_individual_fragments": individual,
            **settings,
        },
    )
    llm_mock.enqueue_writer("She nods slowly.")
    await _drain(handle_turn(cid, "hello"))


async def test_an_individual_fragment_runs_on_its_profile(client, llm_mock):
    seeded = (await client.get("/api/profiles")).json()[0]
    profile = await _create_profile(client, **_FRAGMENT_PRESET)
    await _fragment("pace", model_config_id=profile["id"])
    await _fragment("tone")

    await _individual_turn(client, llm_mock, "conv-profile-routing")

    own = _director_call(llm_mock, "pace")
    assert (own["endpoint"], own["model"]) == (_FRAGMENT_URL, "frag-model")
    assert {k: own["params"][k] for k in _FRAGMENT_PRESET} == _FRAGMENT_PRESET

    # Every other scene step and the moods step stay on the Agent lane.
    agent_calls = [c for c in llm_mock.captured if c["pass"] == "director" and c is not own]
    assert agent_calls
    assert {(c["endpoint"], c["model"]) for c in agent_calls} == {(seeded["endpoint_url"], seeded["model_name"])}

    # The fragment reads the prompt it would have read on the Agent lane.
    other = _director_call(llm_mock, "tone")
    assert own["messages"][:-1] == other["messages"][:-1]
    assert own["tools"] == other["tools"]


async def test_the_combined_director_call_ignores_fragment_profiles(client, llm_mock):
    seeded = (await client.get("/api/profiles")).json()[0]
    profile = await _create_profile(client)
    await _fragment("pace", model_config_id=profile["id"])

    await _individual_turn(client, llm_mock, "conv-profile-combined", individual=False)

    director = [c for c in llm_mock.captured if c["pass"] == "director"]
    assert len(director) == 1
    assert (director[0]["endpoint"], director[0]["model"]) == (seeded["endpoint_url"], seeded["model_name"])


async def test_an_individual_direction_note_runs_on_its_profile(client, llm_mock):
    seeded = (await client.get("/api/profiles")).json()[0]
    profile = await _create_profile(client, **_FRAGMENT_PRESET)
    await _fragment("alpha", "direction_note", label="Alpha heading", model_config_id=profile["id"])
    await _fragment("beta", "direction_note", label="Beta heading")

    await _individual_turn(
        client,
        llm_mock,
        "conv-profile-notes",
        direction_notes_record=True,
        enabled_tools={"direct_scene": False},
    )

    notes = [c for c in llm_mock.captured if c["pass"] == "direction_note"]
    assert len(notes) == 2
    own = next(c for c in notes if "Alpha heading" in json.dumps(c["messages"][-1]))
    other = next(c for c in notes if "Beta heading" in json.dumps(c["messages"][-1]))
    assert (own["endpoint"], own["model"]) == (_FRAGMENT_URL, "frag-model")
    assert {k: own["params"][k] for k in _FRAGMENT_PRESET} == _FRAGMENT_PRESET
    assert (other["endpoint"], other["model"]) == (seeded["endpoint_url"], seeded["model_name"])


# -- migration 8003 ------------------------------------------------------------

_LANE_KEYS = (
    "endpoint_url",
    "api_key",
    "model_name",
    "completion_mode",
    "proxy",
    "temperature",
    "agent_endpoint_url",
    "agent_api_key",
    "agent_model_name",
    "agent_completion_mode",
    "agent_proxy",
    "agent_temperature",
)


def _insert_endpoint(conn: sqlite3.Connection, url: str, mode: str = "chat", proxy: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO endpoints (url, api_key, completion_mode, proxy) VALUES (?, ?, ?, ?)", (url, f"key-{url}", mode, proxy)
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def _insert_config(conn: sqlite3.Connection, endpoint_id: int, model: str, temperature: float) -> int:
    cur = conn.execute(
        "INSERT INTO model_configs (endpoint_id, model_name, temperature) VALUES (?, ?, ?)", (endpoint_id, model, temperature)
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def _legacy_database(db_path: Path) -> dict[str, int]:
    """Endpoint rows shared by several configs, the way the old editor saved them."""
    conn = sqlite3.connect(db_path)
    try:
        shared = _insert_endpoint(conn, "http://shared.local/v1", mode="text", proxy="http://proxy.local:8080")
        writer = _insert_config(conn, shared, "writer-model", 0.9)
        agent = _insert_config(conn, shared, "agent-model", 0.2)
        extra = _insert_config(conn, shared, "extra-model", 0.5)
        conn.execute(
            "UPDATE endpoints SET active_model_config_id = ?, agent_active_model_config_id = ? WHERE id = ?",
            (writer, agent, shared),
        )
        # No writer pointer here: the row keeps the agent's config.
        loose = _insert_endpoint(conn, "http://loose.local/v1")
        first = _insert_config(conn, loose, "first-model", 0.6)
        second = _insert_config(conn, loose, "second-model", 0.7)
        conn.execute("UPDATE endpoints SET agent_active_model_config_id = ? WHERE id = ?", (second, loose))
        conn.execute(
            "UPDATE settings SET active_endpoint_id = ?, agent_endpoint_id = ?, agent_same_as_writer = 0 WHERE id = 1",
            (shared, shared),
        )
        conn.commit()
    finally:
        conn.close()
    return {"shared": shared, "writer": writer, "agent": agent, "extra": extra, "loose": loose, "first": first, "second": second}


def _migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        importlib.import_module("backend.database.migrations.8003_endpoint_profiles").migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _snapshot(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr)  # nosec B608 -- fixed table names
            for table in ("endpoints", "model_configs", "settings")
        }
    finally:
        conn.close()


async def test_8003_gives_each_config_its_own_endpoint_without_moving_a_lane(db_path: Path, monkeypatch):
    monkeypatch.setattr(db_connection, "DB_PATH", str(db_path))
    ids = _legacy_database(db_path)
    lanes_before = {k: (await get_settings()).get(k) for k in _LANE_KEYS}

    _migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        owner = dict(conn.execute("SELECT id, endpoint_id FROM model_configs").fetchall())
        endpoints = {
            row[0]: row[1:]
            for row in conn.execute(
                "SELECT id, url, api_key, completion_mode, proxy, active_model_config_id, agent_active_model_config_id FROM endpoints"
            )
        }
        settings = conn.execute("SELECT active_endpoint_id, agent_endpoint_id FROM settings WHERE id = 1").fetchone()
    finally:
        conn.close()

    assert len(set(owner.values())) == len(owner), "an endpoint row is still shared"
    # Each row keeps the config a lane had selected on it; the rest move to copies.
    assert owner[ids["writer"]] == ids["shared"]
    assert owner[ids["second"]] == ids["loose"]
    for moved in ("agent", "extra"):
        copy = endpoints[owner[ids[moved]]]
        assert copy[:4] == endpoints[ids["shared"]][:4]
        assert copy[4:] == (ids[moved], ids[moved])
    assert endpoints[owner[ids["first"]]][4:] == (ids["first"], ids["first"])
    assert endpoints[ids["shared"]][4:] == (ids["writer"], ids["writer"])
    assert endpoints[ids["loose"]][4:] == (None, ids["second"])
    assert settings == (ids["shared"], owner[ids["agent"]])

    assert {k: (await get_settings()).get(k) for k in _LANE_KEYS} == lanes_before


async def test_8003_changes_nothing_once_every_config_has_its_own_endpoint(db_path: Path):
    _legacy_database(db_path)
    _migrate(db_path)
    after_first = _snapshot(db_path)

    _migrate(db_path)

    assert _snapshot(db_path) == after_first
