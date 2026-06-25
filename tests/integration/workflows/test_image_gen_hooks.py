"""Integration tests for the image_gen workflow's pipeline and trigger hooks.

The `image_gen` workflow registers at import, so these tests exercise the live
hooks against a temp DB. The two LLM passes and the ComfyUI render are stubbed --
both are non-deterministic external systems with no place on a test's path.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest
from fastapi.responses import StreamingResponse

from backend.database import (
    add_message,
    create_character_card,
    create_conversation,
    create_direction_notes,
    get_character_card,
    get_message_by_id,
    get_workflow_attachments_for_message,
)
from backend.workflows import (
    OnDemandCtx,
    PostCtx,
    RegenCtx,
    RerollGenCtx,
    _readonly,
    set_workflow_character_state,
)
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


def _post_ctx(cid: str, char_id: str, draft: str, *, history=(), settings=None) -> PostCtx:
    return PostCtx(
        conversation_id=cid,
        history=history,
        draft=draft,
        effective_msg="hello",
        director_output=MappingProxyType({}),
        settings=MappingProxyType(settings or {}),
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


def _ondemand_ctx(cid: str, char_id: str, history=(), settings=None) -> OnDemandCtx:
    return OnDemandCtx(
        conversation_id=cid,
        history=history,
        last_user_message="hello",
        settings=MappingProxyType(settings or {}),
        client=None,
        character_id=char_id,
        character=None,
    )


async def _seed_reply(cid: str = "conv1", char_id: str = "char1", reply: str = "She smiles.") -> int:
    """Seed a conversation with a user message and an assistant reply; return the
    assistant message id the production path anchors on."""
    await _seed(cid, char_id)
    user_id, _ = await add_message(cid, "user", "hello", 0)
    asst_id, _ = await add_message(cid, "assistant", reply, 1, parent_id=user_id)
    return asst_id


async def test_production_trigger_streams_and_persists(client, monkeypatch):
    cid, char_id = "conv1", "char1"
    asst_id = await _seed_reply(cid, char_id)
    _stub_passes(monkeypatch)
    _stub_render(monkeypatch)

    resp = await client.post(
        f"/api/conversations/{cid}/workflows/{WID}/trigger",
        json={"action": "generate", "message_id": asst_id},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "event: phase_status" in body
    assert "event: image_generated" in body

    atts = await get_workflow_attachments_for_message(asst_id)
    assert len(atts) == 1
    assert atts[0]["workflow_id"] == WID
    assert atts[0]["mime_type"] == "image/png"


async def test_production_generates_without_enable_flag(client, monkeypatch):
    # The per-character enable flag gates only auto-generation; the manual button is
    # an explicit request, so production renders with no flag set.
    cid, char_id = "conv1", "char1"
    asst_id = await _seed_reply(cid, char_id)
    _stub_passes(monkeypatch)
    _stub_render(monkeypatch)

    anchor = await get_message_by_id(asst_id)
    events = [ev async for ev in hooks._generate_stream(_ondemand_ctx(cid, char_id), anchor)]

    assert any("event: image_generated" in e and "null" not in e for e in events)
    assert len(await get_workflow_attachments_for_message(asst_id)) == 1


async def test_production_completes_when_insert_fails(client, monkeypatch):
    # An insert failure must not abort the stream: the terminal events still flow so
    # the client unblocks (degraded to no image) instead of hanging on a stream that
    # never closes.
    cid, char_id = "conv1", "char1"
    asst_id = await _seed_reply(cid, char_id)
    _stub_passes(monkeypatch)
    _stub_render(monkeypatch)

    async def boom_insert(*args, **kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(hooks, "insert_workflow_attachment", boom_insert)

    anchor = await get_message_by_id(asst_id)
    events = [ev async for ev in hooks._generate_stream(_ondemand_ctx(cid, char_id), anchor)]

    assert any("event: image_generated" in e and "null" in e for e in events)
    assert any("event: phase_status" in e and "done" in e for e in events)


async def test_production_degrades_on_comfy_error(client, monkeypatch):
    cid, char_id = "conv1", "char1"
    asst_id = await _seed_reply(cid, char_id)
    _stub_passes(monkeypatch)

    async def boom(graph, *, base_url, timeout, poll_interval=0.75):
        raise ComfyError("unreachable")

    monkeypatch.setattr(hooks, "generate_image", boom)

    anchor = await get_message_by_id(asst_id)
    events = [ev async for ev in hooks._generate_stream(_ondemand_ctx(cid, char_id), anchor)]

    assert any("event: image_generated" in e and "null" in e for e in events)
    assert await get_workflow_attachments_for_message(asst_id) == []


async def test_production_rejects_non_assistant_target(client):
    cid, char_id = "conv1", "char1"
    asst_id = await _seed_reply(cid, char_id)
    ctx = _ondemand_ctx(cid, char_id)
    anchor = await get_message_by_id(asst_id)
    assert anchor is not None
    user_id = anchor["parent_id"]

    assert "error" in await hooks._generate(ctx, {})
    assert "error" in await hooks._generate(ctx, {"message_id": "x"})
    assert "error" in await hooks._generate(ctx, {"message_id": 999999})
    assert "error" in await hooks._generate(ctx, {"message_id": user_id})
    ok = await hooks._generate(ctx, {"message_id": asst_id})
    assert isinstance(ok, StreamingResponse)


async def test_production_prefix_carries_system_framing(client, monkeypatch):
    # The prefix must carry the system prompt + character framing the auto path
    # gets, not bare role/content history.
    cid, char_id = "conv1", "char1"
    asst_id = await _seed_reply(cid, char_id)
    captured = {}

    async def capture_analyze(**kwargs):
        captured["prefix"] = kwargs.get("prefix")
        yield {"type": "result", "args": _SCENE}

    async def fake_compose(**kwargs):
        yield {"type": "result", "args": {"positive_prompt": "x"}}

    monkeypatch.setattr(hooks, "analyze_scene", capture_analyze)
    monkeypatch.setattr(hooks, "compose_prompt", fake_compose)
    _stub_render(monkeypatch)

    ctx = OnDemandCtx(
        conversation_id=cid,
        history=(),
        last_user_message="hello",
        settings=MappingProxyType({"system_prompt": "You are a test bot."}),
        client=None,
        character_id=char_id,
        character=_readonly(await get_character_card(char_id)),
    )
    anchor = await get_message_by_id(asst_id)
    _ = [ev async for ev in hooks._generate_stream(ctx, anchor)]

    prefix = captured["prefix"]
    assert prefix[0]["role"] == "system"
    assert "You are a test bot." in prefix[0]["content"]


async def test_regenerate_uses_rich_prefix(client, monkeypatch):
    # regenerate shares the same generation core + rebuilt prefix as the auto and
    # production paths, so its re-render carries the system prompt + framing too.
    cid, char_id = "conv1", "char1"
    asst_id = await _seed_reply(cid, char_id)
    captured = {}

    async def capture_analyze(**kwargs):
        captured["prefix"] = kwargs.get("prefix")
        yield {"type": "result", "args": _SCENE}

    async def fake_compose(**kwargs):
        yield {"type": "result", "args": {"positive_prompt": "x"}}

    monkeypatch.setattr(hooks, "analyze_scene", capture_analyze)
    monkeypatch.setattr(hooks, "compose_prompt", fake_compose)
    _stub_render(monkeypatch)

    ctx = RegenCtx(
        conversation_id=cid,
        message_id=asst_id,
        attachment_id=1,
        original_attachment=MappingProxyType({}),
        history=(),
        last_user_message="hello",
        settings=MappingProxyType({"system_prompt": "You are a test bot."}),
        client=None,
        character_id=char_id,
        character=_readonly(await get_character_card(char_id)),
    )
    out = await hooks.regenerate(ctx, {})

    assert len(out) == 1
    assert out[0]["workflow_id"] == WID
    assert captured["prefix"][0]["role"] == "system"
    assert "You are a test bot." in captured["prefix"][0]["content"]


# --- direction-note injection into the two passes ----------------------------


def _capture_passes(monkeypatch) -> dict:
    """Stub both passes to record the direction_notes block each receives, returning a
    usable scene/prompt so the surrounding render path still completes."""
    seen: dict = {}

    async def cap_analyze(**kwargs):
        seen["analyze"] = kwargs.get("direction_notes")
        yield {"type": "result", "args": _SCENE}

    async def cap_compose(**kwargs):
        seen["compose"] = kwargs.get("direction_notes")
        yield {"type": "result", "args": {"positive_prompt": "a tester, hat"}}

    monkeypatch.setattr(hooks, "analyze_scene", cap_analyze)
    monkeypatch.setattr(hooks, "compose_prompt", cap_compose)
    return seen


async def _seed_note(cid: str, char_id: str, *, content: str = "She lost her left arm.") -> dict:
    """Seed a reply with one direction note on it; return a history-message dict carrying
    the anchor's id and turn_index, shaped like the rows the hooks read from ctx.history."""
    asst_id = await _seed_reply(cid, char_id)
    await create_direction_notes(
        cid,
        asst_id,
        [{"interactive_fragment_id": "characterization", "interactive_fragment_label": "Characterization", "content": content}],
    )
    msg = await get_message_by_id(asst_id)
    assert msg is not None
    return {"id": asst_id, "role": "assistant", "content": msg["content"], "turn_index": msg["turn_index"]}


async def test_resolve_direction_notes_renders_when_injecting(client):
    cid, char_id = "conv1", "char1"
    hist_msg = await _seed_note(cid, char_id)
    ctx = _ondemand_ctx(cid, char_id, settings={"direction_notes_inject": "director"})
    block = await hooks._resolve_direction_notes(ctx, [hist_msg])
    assert "**Direction Notes**" in block
    assert "Characterization" in block
    assert "She lost her left arm." in block


async def test_resolve_direction_notes_off_returns_empty(client):
    cid, char_id = "conv1", "char1"
    hist_msg = await _seed_note(cid, char_id)
    ctx = _ondemand_ctx(cid, char_id, settings={"direction_notes_inject": "off"})
    assert await hooks._resolve_direction_notes(ctx, [hist_msg]) == ""


async def test_resolve_direction_notes_empty_without_notes(client):
    cid, char_id = await _seed()
    ctx = _ondemand_ctx(cid, char_id, settings={"direction_notes_inject": "both"})
    # Injection is on, but the branch carries no notes, so the block is empty.
    assert await hooks._resolve_direction_notes(ctx, [{"id": 1, "turn_index": 0}]) == ""


async def test_post_pipeline_threads_notes_into_both_passes(client, monkeypatch):
    cid, char_id = "conv1", "char1"
    hist_msg = await _seed_note(cid, char_id)
    await set_workflow_character_state(char_id, WID, {"enabled": True, "prompt": "a tester"})
    seen = _capture_passes(monkeypatch)
    _stub_render(monkeypatch)

    ctx = _post_ctx(cid, char_id, "She smiles.", history=(hist_msg,), settings={"direction_notes_inject": "both"})
    _ = [ev async for ev in hooks.post_pipeline(ctx)]

    # Both passes receive the same rendered block, so the scene analyzer and the prompt
    # composer agree on the standing direction.
    assert "She lost her left arm." in (seen["analyze"] or "")
    assert "**Direction Notes**" in (seen["analyze"] or "")
    assert seen["compose"] == seen["analyze"]
