"""Tests for GET /api/secondary-workflows (smoke 19.5)."""

from __future__ import annotations

from ._fixtures import make_workflow, register_for_test


async def test_empty_registry_returns_empty_list(client):
    resp = await client.get("/api/secondary-workflows")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_registered_workflow_appears_with_all_fields(client):
    async def regen(regen_ctx, payload):
        return []

    wf = make_workflow(
        "scene_cg",
        display_name="Scene CG",
        regenerate=regen,
        config_schema={"type": "object"},
        config_defaults={"style": "noir"},
        auto_regen_button=False,
    )
    with register_for_test(wf):
        resp = await client.get("/api/secondary-workflows")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {
            "id": "scene_cg",
            "display_name": "Scene CG",
            "config_schema": {"type": "object"},
            "config_defaults": {"style": "noir"},
            "supports_regenerate": True,
            "auto_regen_button": False,
        }
    ]


async def test_workflow_without_regenerate_reports_supports_regenerate_false(client):
    wf = make_workflow("tts", display_name="TTS")
    with register_for_test(wf):
        resp = await client.get("/api/secondary-workflows")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "tts"
    assert body[0]["supports_regenerate"] is False
    assert body[0]["auto_regen_button"] is True
    assert body[0]["config_schema"] is None


async def test_priority_id_iteration_order(client):
    high = make_workflow("aaa", display_name="High prio low id", priority=10)
    low_a = make_workflow("zzz", display_name="Low prio late id", priority=0)
    low_b = make_workflow("mmm", display_name="Low prio mid id", priority=0)
    with register_for_test(high), register_for_test(low_a), register_for_test(low_b):
        resp = await client.get("/api/secondary-workflows")
    ids = [w["id"] for w in resp.json()]
    assert ids == ["mmm", "zzz", "aaa"]
