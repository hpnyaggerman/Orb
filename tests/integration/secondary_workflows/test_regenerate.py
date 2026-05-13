"""Tests for POST /api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate.

Covers the regenerate dispatch route end-to-end (smoke 19.12): append-only
guarantee, dispatcher-fixed source/workflow_id/parent_attachment_id, root
walking, payload pass-through, every 404 surface, per-entry resilience to
storage failures, and the 500-on-hook-raise no-write guarantee.
"""

from __future__ import annotations

import os
import tempfile

from backend.database import (
    add_message,
    add_workflow_attachment,
    get_attachments_for_message,
    set_active_leaf,
)

from ._fixtures import make_workflow, register_for_test


async def _seed_conversation_with_message(client) -> tuple[str, int]:
    resp = await client.post("/api/conversations", json={"title": "Regenerate test"})
    assert resp.status_code == 200
    cid = resp.json()["id"]
    mid = await add_message(cid, "assistant", "scene draft", 0)
    await set_active_leaf(cid, mid)
    return cid, mid


async def _seed_workflow_attachment(mid: int, workflow_id: str = "scene_cg") -> int:
    return await add_workflow_attachment(
        mid,
        {
            "filename": "root.png",
            "mime": "image/png",
            "data": b"root-bytes",
            "source": f"workflow:{workflow_id}",
            "workflow_id": workflow_id,
        },
    )


async def test_missing_conversation_returns_404(client):
    resp = await client.post(
        "/api/conversations/no-such/messages/1/attachments/1/regenerate",
        json={},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Conversation not found"}


async def test_missing_attachment_returns_404(client):
    cid, _ = await _seed_conversation_with_message(client)
    resp = await client.post(
        f"/api/conversations/{cid}/messages/1/attachments/99999/regenerate",
        json={},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Attachment not found on this message"}


async def test_attachment_belongs_to_different_message_returns_404(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)
    other_mid = await add_message(cid, "user", "second", 1, parent_id=mid)
    resp = await client.post(
        f"/api/conversations/{cid}/messages/{other_mid}/attachments/{aid}/regenerate",
        json={},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Attachment not found on this message"}


async def test_user_source_attachment_returns_404(client, db):
    cid, mid = await _seed_conversation_with_message(client)
    async with db.execute(
        "INSERT INTO message_attachments (message_id, mime_type, data_b64, filename, size, created_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (mid, "image/png", "Zm9v", "user.png", 3),
    ) as cur:
        aid = cur.lastrowid
    await db.commit()
    resp = await client.post(
        f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
        json={},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Attachment is not workflow-produced"}


async def test_workflow_not_registered_returns_404(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid, workflow_id="ghost")
    resp = await client.post(
        f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
        json={},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Workflow 'ghost' is not registered or has no regenerate handler"}


async def test_workflow_without_regenerate_hook_returns_404(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid, workflow_id="tts")
    wf = make_workflow("tts", display_name="TTS")
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Workflow 'tts' is not registered or has no regenerate handler"}


async def test_message_not_on_active_path_returns_404(client):
    resp = await client.post("/api/conversations", json={"title": "Inactive path"})
    cid = resp.json()["id"]
    mid = await add_message(cid, "assistant", "off-path", 0)
    # Deliberately skip set_active_leaf so get_messages returns [].
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return []

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Message not found in conversation"}


async def test_happy_path_inserts_dispatcher_fixed_row(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return [{"filename": "variant.png", "mime": "image/png", "data": b"new-bytes"}]

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    assert resp.status_code == 200
    new_ids = resp.json()["attachments"]
    assert len(new_ids) == 1

    rows = await get_attachments_for_message(mid)
    new_row = next(r for r in rows if r["id"] == new_ids[0])
    assert new_row["source"] == "workflow:scene_cg"
    assert new_row["workflow_id"] == "scene_cg"
    assert new_row["parent_attachment_id"] == aid


async def test_dispatcher_overwrites_impersonation_attempts(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return [
            {
                "filename": "stolen.png",
                "mime": "image/png",
                "data": b"bytes",
                "source": "user",
                "workflow_id": "other",
                "parent_attachment_id": 99999,
            }
        ]

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    new_id = resp.json()["attachments"][0]
    rows = await get_attachments_for_message(mid)
    new_row = next(r for r in rows if r["id"] == new_id)
    assert new_row["source"] == "workflow:scene_cg"
    assert new_row["workflow_id"] == "scene_cg"
    assert new_row["parent_attachment_id"] == aid


async def test_empty_list_return_is_valid_noop(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return []

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    assert resp.status_code == 200
    assert resp.json() == {"attachments": []}


async def test_non_list_return_treated_as_empty(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return {"not": "a list"}

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    assert resp.status_code == 200
    assert resp.json() == {"attachments": []}


async def test_non_dict_entries_skipped(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return [
            "not-a-dict",
            {"filename": "ok.png", "mime": "image/png", "data": b"good"},
            42,
        ]

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    new_ids = resp.json()["attachments"]
    assert len(new_ids) == 1
    rows = await get_attachments_for_message(mid)
    new_row = next(r for r in rows if r["id"] == new_ids[0])
    assert new_row["filename"] == "ok.png"


async def test_hook_raise_returns_500_and_writes_no_rows(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)
    pre_rows = await get_attachments_for_message(mid)

    async def regen(ctx, payload):
        raise RuntimeError("hook explodes")

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Regenerate handler raised; see server logs"}
    post_rows = await get_attachments_for_message(mid)
    assert {r["id"] for r in pre_rows} == {r["id"] for r in post_rows}


async def test_per_entry_skip_on_empty_bytes_continues_with_valid_entries(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return [
            {"filename": "first.png", "mime": "image/png", "data": b"first"},
            {"filename": "empty.png", "mime": "image/png", "data": b""},
            {"filename": "third.png", "mime": "image/png", "data": b"third"},
        ]

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    new_ids = resp.json()["attachments"]
    assert len(new_ids) == 2
    rows = await get_attachments_for_message(mid)
    new_rows = [r for r in rows if r["id"] in new_ids]
    filenames = {r["filename"] for r in new_rows}
    assert filenames == {"first.png", "third.png"}


async def test_per_entry_skip_on_unreadable_path_continues(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return [
            {"filename": "ok.png", "mime": "image/png", "data": b"ok-bytes"},
            {"filename": "missing.png", "mime": "image/png", "path": "/no/such/path.png"},
        ]

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={},
        )
    new_ids = resp.json()["attachments"]
    assert len(new_ids) == 1
    rows = await get_attachments_for_message(mid)
    new_row = next(r for r in rows if r["id"] == new_ids[0])
    assert new_row["filename"] == "ok.png"


async def test_path_shaped_entry_normalized_to_bytes(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
        f.write(b"on-disk-bytes")
        path = f.name
    try:

        async def regen(ctx, payload):
            return [{"filename": "fromdisk.png", "mime": "image/png", "path": path}]

        wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
        with register_for_test(wf):
            resp = await client.post(
                f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
                json={},
            )
    finally:
        os.unlink(path)
    new_ids = resp.json()["attachments"]
    assert len(new_ids) == 1


async def test_root_walking_flattens_chain(client):
    cid, mid = await _seed_conversation_with_message(client)
    root = await _seed_workflow_attachment(mid)
    sibling = await add_workflow_attachment(
        mid,
        {
            "filename": "sibling.png",
            "mime": "image/png",
            "data": b"sibling-bytes",
            "source": "workflow:scene_cg",
            "workflow_id": "scene_cg",
            "parent_attachment_id": root,
        },
    )

    async def regen(ctx, payload):
        return [{"filename": "grandchild.png", "mime": "image/png", "data": b"grandchild"}]

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        resp = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{sibling}/regenerate",
            json={},
        )
    new_id = resp.json()["attachments"][0]
    rows = await get_attachments_for_message(mid)
    new_row = next(r for r in rows if r["id"] == new_id)
    assert (
        new_row["parent_attachment_id"] == root
    ), "regen on a sibling must produce a row whose parent is the root, not the sibling"


async def test_payload_passthrough_reaches_hook(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)
    captured: list[dict] = []

    async def regen(ctx, payload):
        captured.append(payload)
        return []

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        first = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
            json={"style": "noir"},
        )
        second = await client.post(
            f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert captured[0] == {"style": "noir"}
    assert captured[1] == {}


async def test_append_only_preserves_originals(client):
    cid, mid = await _seed_conversation_with_message(client)
    aid = await _seed_workflow_attachment(mid)

    async def regen(ctx, payload):
        return [{"filename": "new.png", "mime": "image/png", "data": b"new"}]

    wf = make_workflow("scene_cg", display_name="Scene CG", regenerate=regen)
    with register_for_test(wf):
        for _ in range(3):
            resp = await client.post(
                f"/api/conversations/{cid}/messages/{mid}/attachments/{aid}/regenerate",
                json={},
            )
            assert resp.status_code == 200

    rows = await get_attachments_for_message(mid)
    root = next(r for r in rows if r["id"] == aid)
    assert root["filename"] == "root.png"
    assert root["parent_attachment_id"] is None
    siblings = [r for r in rows if r["parent_attachment_id"] == aid]
    assert len(siblings) == 3
