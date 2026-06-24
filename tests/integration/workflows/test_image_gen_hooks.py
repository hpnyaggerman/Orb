"""Integration tests for the image_gen workflow's pipeline and trigger hooks.

The `image_gen` workflow registers at import, so these tests exercise the live
hooks against a temp DB. The two LLM passes and the ComfyUI render are stubbed --
both are non-deterministic external systems with no place on a test's path.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from backend.database import create_character_card, create_conversation
from backend.workflows import PostCtx, RerollGenCtx, set_workflow_character_state
from backend.workflows.image_gen import hooks
from backend.workflows.image_gen.comfy import ComfyError

WID = "image_gen"

_SCENE = {
    "characters_present": ["Tester"],
    "outfits": [{"character": "Tester", "added_articles": ["hat"], "removed_default_articles": []}],
    "anchors": [],
    "positions": [],
    "poses": [],
    "actions": [],
}


def _post_ctx(cid: str, char_id: str, draft: str) -> PostCtx:
    return PostCtx(
        conversation_id=cid,
        history=(),
        draft=draft,
        effective_msg="hello",
        director_output=MappingProxyType({}),
        settings=MappingProxyType({}),
        prefix=(),
        enabled_tools=MappingProxyType({}),
        turn_scratch={},
        client=None,
        kv_tracker=None,
        schema_overrides=MappingProxyType({}),
        character_id=char_id,
    )


async def _seed(cid: str = "conv1", char_id: str = "char1") -> tuple[str, str]:
    await create_character_card({"id": char_id, "name": "Tester"})
    await create_conversation(cid, "Title", "Tester", "scene", character_card_id=char_id)
    return cid, char_id


def _stub_passes(monkeypatch, *, scene=_SCENE, positive="a tester, hat"):
    async def fake_analyze(**kwargs):
        yield {"type": "result", "args": scene}

    async def fake_compose(**kwargs):
        yield {"type": "result", "args": {"positive_prompt": positive}}

    monkeypatch.setattr(hooks, "analyze_scene", fake_analyze)
    monkeypatch.setattr(hooks, "compose_prompt", fake_compose)


def _stub_render(monkeypatch, *, data=b"PNGDATA", mime="image/png"):
    async def fake_generate(graph, *, base_url, timeout, poll_interval=0.75):
        return data, mime

    monkeypatch.setattr(hooks, "generate_image", fake_generate)


async def test_post_pipeline_attaches_image_when_enabled(client, monkeypatch):
    cid, char_id = await _seed()
    await set_workflow_character_state(char_id, WID, {"enabled": True, "prompt": "a tester"})
    _stub_passes(monkeypatch)
    _stub_render(monkeypatch)

    events = [ev async for ev in hooks.post_pipeline(_post_ctx(cid, char_id, "She smiles."))]

    attach = [e for e in events if e.get("type") == "attach_artifact"]
    assert len(attach) == 1
    att = attach[0]["attachment"]
    assert att["workflow_id"] == WID
    assert att["source"] == f"workflow:{WID}"
    assert att["mime"] == "image/png"
    assert att["data"] == b"PNGDATA"
    assert isinstance(att["seed"], str) and att["seed"]
    int(att["seed"], 16)  # seed is stored as hex so rehydrate can decode it
    md = att["generation_metadata"]
    assert "a tester, hat" in md["positive"]
    assert "comfy_url" in md and "negative" in md
    assert "seed" not in md
    assert any(e.get("event") == "phase_status" for e in events)


async def test_post_pipeline_skips_when_disabled(client, monkeypatch):
    cid, char_id = await _seed()
    await set_workflow_character_state(char_id, WID, {"enabled": False, "prompt": "x"})
    _stub_passes(monkeypatch)
    _stub_render(monkeypatch)

    events = [ev async for ev in hooks.post_pipeline(_post_ctx(cid, char_id, "Hi."))]
    assert events == []


async def test_post_pipeline_default_off_without_state(client, monkeypatch):
    cid, char_id = await _seed()
    _stub_passes(monkeypatch)
    _stub_render(monkeypatch)

    events = [ev async for ev in hooks.post_pipeline(_post_ctx(cid, char_id, "Hi."))]
    assert events == []


async def test_post_pipeline_degrades_on_comfy_error(client, monkeypatch):
    cid, char_id = await _seed()
    await set_workflow_character_state(char_id, WID, {"enabled": True, "prompt": "a tester"})
    _stub_passes(monkeypatch)

    async def boom(graph, *, base_url, timeout, poll_interval=0.75):
        raise ComfyError("unreachable")

    monkeypatch.setattr(hooks, "generate_image", boom)

    events = [ev async for ev in hooks.post_pipeline(_post_ctx(cid, char_id, "Hi."))]
    assert not any(e.get("type") == "attach_artifact" for e in events)
    assert any(e.get("event") == "phase_status" and e["data"].get("state") == "done" for e in events)


async def test_post_pipeline_degrades_on_empty_scene(client, monkeypatch):
    cid, char_id = await _seed()
    await set_workflow_character_state(char_id, WID, {"enabled": True})
    _stub_passes(monkeypatch, scene={"characters_present": [], "outfits": []})
    _stub_render(monkeypatch)

    events = [ev async for ev in hooks.post_pipeline(_post_ctx(cid, char_id, "Hi."))]
    assert not any(e.get("type") == "attach_artifact" for e in events)


async def test_reroll_gen_renders_without_running_passes(client, monkeypatch):
    cid, _ = await _seed()

    async def fail_analyze(**kwargs):
        raise AssertionError("analyze_scene must not run on reroll")
        yield  # pragma: no cover

    async def fail_compose(**kwargs):
        raise AssertionError("compose_prompt must not run on reroll")
        yield  # pragma: no cover

    monkeypatch.setattr(hooks, "analyze_scene", fail_analyze)
    monkeypatch.setattr(hooks, "compose_prompt", fail_compose)

    captured = {}

    async def fake_generate(graph, *, base_url, timeout, poll_interval=0.75):
        captured["seed"] = graph["19"]["inputs"]["seed"]
        captured["positive"] = graph["11"]["inputs"]["text"]
        return b"REROLL", "image/png"

    monkeypatch.setattr(hooks, "generate_image", fake_generate)

    ctx = RerollGenCtx(
        conversation_id=cid,
        message_id=1,
        attachment_id=1,
        original_attachment=MappingProxyType({}),
        settings=MappingProxyType({}),
        client=None,
    )
    params = {
        "positive": "a tester, hat",
        "negative": "bad",
        "cfg": 5.0,
        "steps": 40,
        "width": 1536,
        "height": 1152,
        "comfy_url": "http://comfy",
    }
    out = await hooks.reroll_gen(ctx, params, "1a2b")
    assert out == b"REROLL"
    assert captured["seed"] == int("1a2b", 16) % (2**63)
    assert captured["positive"] == "a tester, hat"


async def test_reroll_gen_raises_without_prompt(client):
    ctx = RerollGenCtx(
        conversation_id="c",
        message_id=1,
        attachment_id=1,
        original_attachment=MappingProxyType({}),
        settings=MappingProxyType({}),
        client=None,
    )
    with pytest.raises(ValueError):
        await hooks.reroll_gen(ctx, {"negative": "x"}, "ab")


async def test_manifest_lists_image_gen(client):
    resp = await client.get("/api/workflows")
    assert resp.status_code == 200
    entries = {w["id"]: w for w in resp.json()}
    assert WID in entries
    assert entries[WID]["display_name"] == "Image Generation"
    assert entries[WID]["config_schema"]


async def test_config_round_trip(client):
    put = await client.put(f"/api/workflows/{WID}/config", json={"config": {"comfy_url": "http://host:8188", "cfg": 7}})
    assert put.status_code == 200
    got = await client.get(f"/api/workflows/{WID}/config")
    assert got.json()["config"]["cfg"] == 7


async def test_char_state_round_trip(client):
    cid, _ = await _seed()
    base = f"/api/conversations/{cid}/workflows/{WID}/trigger"

    got = await client.post(base, json={"action": "get_char_state"})
    assert got.status_code == 200
    assert got.json()["enabled"] is False

    saved = await client.post(base, json={"action": "set_char_state", "enabled": True, "prompt": "a knight"})
    assert saved.json()["ok"] is True

    again = await client.post(base, json={"action": "get_char_state"})
    assert again.json()["enabled"] is True
    assert again.json()["prompt"] == "a knight"


async def test_on_demand_test_unifies_config_without_llm(client, monkeypatch):
    cid, char_id = await _seed()
    await set_workflow_character_state(char_id, WID, {"enabled": True, "prompt": "a knight, plate armor"})

    async def fail(**kwargs):
        raise AssertionError("a config test must not run the LLM passes")
        yield  # pragma: no cover

    monkeypatch.setattr(hooks, "analyze_scene", fail)
    monkeypatch.setattr(hooks, "compose_prompt", fail)

    captured = {}

    async def fake_generate(graph, *, base_url, timeout, poll_interval=0.75):
        captured["positive"] = graph["11"]["inputs"]["text"]
        captured["negative"] = graph["12"]["inputs"]["text"]
        return b"PNG", "image/png"

    monkeypatch.setattr(hooks, "generate_image", fake_generate)

    resp = await client.post(
        f"/api/conversations/{cid}/workflows/{WID}/trigger",
        json={"action": "test", "config": {"artist_tags": "by someone"}},
    )
    assert resp.status_code == 200
    assert "image_b64" in resp.json()
    # The single prompt unifies the prepended tags with the character prompt; the
    # negative falls back to its baked default.
    assert "a knight, plate armor" in captured["positive"]
    assert "by someone" in captured["positive"]
    assert "sitting in front of a table" in captured["positive"]
    assert captured["negative"]
