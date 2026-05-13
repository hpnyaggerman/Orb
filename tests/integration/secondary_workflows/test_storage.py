"""Integration tests for workflow-storage helpers.

Covers state-slot isolation across per-conversation, per-message, and global
workflow_config tiers, plus the add_workflow_attachment writer (impersonation
guards, empty-bytes rejection, path-to-bytes normalization).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from backend.database import (
    add_message,
    add_workflow_attachment,
    get_attachments_for_message,
    get_workflow_config,
    get_workflow_message_state,
    get_workflow_state,
    set_workflow_config,
    set_workflow_message_state,
    set_workflow_state,
)


async def _new_conversation(client) -> str:
    resp = await client.post("/api/conversations", json={"title": "t"})
    assert resp.status_code == 200
    return resp.json()["id"]


# --------------------------------------------------------------------------
# Workflow state slot isolation
# --------------------------------------------------------------------------


async def test_per_conversation_slot_isolation(client):
    cid = await _new_conversation(client)

    await set_workflow_state(cid, "a", {"x": 1})
    await set_workflow_state(cid, "b", {"y": 2})
    assert (await get_workflow_state(cid, "a")) == {"x": 1}

    await set_workflow_state(cid, "a", {"x": 10})
    assert (await get_workflow_state(cid, "b")) == {"y": 2}

    await set_workflow_state(cid, "a", None)
    assert (await get_workflow_state(cid, "a")) is None
    assert (await get_workflow_state(cid, "b")) == {"y": 2}


async def test_concurrent_writes_distinct_slots_do_not_race(client):
    cid = await _new_conversation(client)

    await asyncio.gather(
        set_workflow_state(cid, "p", {"v": 1}),
        set_workflow_state(cid, "q", {"v": 2}),
    )
    assert (await get_workflow_state(cid, "p")) == {"v": 1}
    assert (await get_workflow_state(cid, "q")) == {"v": 2}


async def test_per_message_slot_isolation(client):
    cid = await _new_conversation(client)
    mid_1 = await add_message(cid, "user", "hi", 0, None)
    mid_2 = await add_message(cid, "assistant", "hello", 0, mid_1)

    await set_workflow_message_state(mid_1, "a", {"emotion": "happy"})
    await set_workflow_message_state(mid_1, "b", {"facts": ["x"]})
    await set_workflow_message_state(mid_2, "a", {"emotion": "sad"})

    assert (await get_workflow_message_state(mid_1, "a")) == {"emotion": "happy"}
    assert (await get_workflow_message_state(mid_1, "b")) == {"facts": ["x"]}
    assert (await get_workflow_message_state(mid_2, "a")) == {"emotion": "sad"}

    await set_workflow_message_state(mid_1, "a", {"emotion": "neutral"})
    assert (await get_workflow_message_state(mid_1, "b")) == {"facts": ["x"]}

    await set_workflow_message_state(mid_1, "a", None)
    assert (await get_workflow_message_state(mid_1, "a")) is None
    assert (await get_workflow_message_state(mid_1, "b")) == {"facts": ["x"]}
    assert (await get_workflow_message_state(mid_2, "a")) == {"emotion": "sad"}


async def test_per_message_state_dies_with_message(client):
    """Deleting the message must drop its workflow_state slot automatically."""
    cid = await _new_conversation(client)
    mid = await add_message(cid, "user", "hi", 0, None)

    await set_workflow_message_state(mid, "a", {"k": "v"})
    assert (await get_workflow_message_state(mid, "a")) == {"k": "v"}

    from backend.database import delete_message_with_descendants

    await delete_message_with_descendants(cid, mid)
    assert (await get_workflow_message_state(mid, "a")) is None


async def test_state_helpers_noop_on_missing_row(client):
    """payload=None / non-None against a missing key is a silent no-op, not an error."""
    # Missing conversation
    await set_workflow_state("no-such-conv", "a", {"x": 1})
    assert (await get_workflow_state("no-such-conv", "a")) is None
    await set_workflow_state("no-such-conv", "a", None)

    # Missing message
    await set_workflow_message_state(999_999, "a", {"x": 1})
    assert (await get_workflow_message_state(999_999, "a")) is None


# --------------------------------------------------------------------------
# add_workflow_attachment helper
# --------------------------------------------------------------------------


async def test_add_workflow_attachment_happy_path(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)

    att_id = await add_workflow_attachment(
        msg_id,
        {
            "filename": "scene.png",
            "mime": "image/png",
            "data": b"\x89PNG\r\n\x1a\n",
            "source": "workflow:scene_cg",
            "workflow_id": "scene_cg",
        },
    )
    assert isinstance(att_id, int)

    atts = await get_attachments_for_message(msg_id)
    assert any(a["id"] == att_id and a["source"] == "workflow:scene_cg" for a in atts)
    row = next(a for a in atts if a["id"] == att_id)
    assert row["workflow_id"] == "scene_cg"
    assert row["parent_attachment_id"] is None
    assert row["annotation"] is None
    assert row["mime_type"] == "image/png"
    assert row["filename"] == "scene.png"
    assert row["size"] == len(b"\x89PNG\r\n\x1a\n")


async def test_add_workflow_attachment_path_shape_is_normalized(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"some-bytes")
        path = f.name
    try:
        att_id = await add_workflow_attachment(
            msg_id,
            {
                "filename": "via-path.bin",
                "mime": "application/octet-stream",
                "path": path,
                "source": "workflow:scene_cg",
                "workflow_id": "scene_cg",
            },
        )
    finally:
        os.unlink(path)

    atts = await get_attachments_for_message(msg_id)
    row = next(a for a in atts if a["id"] == att_id)
    assert row["size"] == len(b"some-bytes")


async def test_add_workflow_attachment_annotation_and_parent_persist(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)

    root_id = await add_workflow_attachment(
        msg_id,
        {
            "filename": "root.png",
            "mime": "image/png",
            "data": b"root-bytes",
            "source": "workflow:scene_cg",
            "workflow_id": "scene_cg",
            "annotation": "A moonlit garden.",
        },
    )
    child_id = await add_workflow_attachment(
        msg_id,
        {
            "filename": "variant.png",
            "mime": "image/png",
            "data": b"variant-bytes",
            "source": "workflow:scene_cg",
            "workflow_id": "scene_cg",
            "parent_attachment_id": root_id,
        },
    )

    atts = {a["id"]: a for a in await get_attachments_for_message(msg_id)}
    assert atts[root_id]["annotation"] == "A moonlit garden."
    assert atts[root_id]["parent_attachment_id"] is None
    assert atts[child_id]["parent_attachment_id"] == root_id


async def test_add_workflow_attachment_impersonation_guard_source(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)
    with pytest.raises(ValueError):
        await add_workflow_attachment(
            msg_id,
            {
                "filename": "fake.png",
                "mime": "image/png",
                "data": b"...",
                "source": "user",
                "workflow_id": "scene_cg",
            },
        )


async def test_add_workflow_attachment_empty_workflow_id(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)
    with pytest.raises(ValueError):
        await add_workflow_attachment(
            msg_id,
            {
                "filename": "fake.png",
                "mime": "image/png",
                "data": b"...",
                "source": "workflow:scene_cg",
                "workflow_id": "",
            },
        )


async def test_add_workflow_attachment_empty_inline_bytes(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)
    with pytest.raises(ValueError):
        await add_workflow_attachment(
            msg_id,
            {
                "filename": "void.png",
                "mime": "image/png",
                "data": b"",
                "source": "workflow:scene_cg",
                "workflow_id": "scene_cg",
            },
        )


async def test_add_workflow_attachment_empty_path_file(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)
    with tempfile.NamedTemporaryFile(delete=False) as f:
        empty_path = f.name
    try:
        with pytest.raises(ValueError):
            await add_workflow_attachment(
                msg_id,
                {
                    "filename": "void.png",
                    "mime": "image/png",
                    "path": empty_path,
                    "source": "workflow:scene_cg",
                    "workflow_id": "scene_cg",
                },
            )
    finally:
        os.unlink(empty_path)


async def test_add_workflow_attachment_data_and_path_both_present(client):
    cid = await _new_conversation(client)
    msg_id = await add_message(cid, "assistant", "hi", 0, None)
    with pytest.raises(ValueError):
        await add_workflow_attachment(
            msg_id,
            {
                "filename": "either.png",
                "mime": "image/png",
                "data": b"...",
                "path": "/tmp/whatever",
                "source": "workflow:scene_cg",
                "workflow_id": "scene_cg",
            },
        )


async def test_add_workflow_attachment_missing_message(client):  # noqa: ARG001 (client triggers DB init)
    with pytest.raises(LookupError):
        await add_workflow_attachment(
            999_999,
            {
                "filename": "x.png",
                "mime": "image/png",
                "data": b"...",
                "source": "workflow:scene_cg",
                "workflow_id": "scene_cg",
            },
        )


# --------------------------------------------------------------------------
# workflow_config helpers
# --------------------------------------------------------------------------


async def test_workflow_config_empty_slot_returns_empty_dict(client):  # noqa: ARG001
    assert (await get_workflow_config("tts")) == {}


async def test_workflow_config_get_set_round_trip(client):  # noqa: ARG001
    await set_workflow_config("tts", {"enabled": True, "volume": 0.75})
    assert (await get_workflow_config("tts")) == {"enabled": True, "volume": 0.75}


async def test_workflow_config_slot_isolation(client):  # noqa: ARG001
    await set_workflow_config("tts", {"enabled": True})
    await set_workflow_config("cg", {"style": "anime"})
    assert (await get_workflow_config("tts")) == {"enabled": True}
    assert (await get_workflow_config("cg")) == {"style": "anime"}


async def test_workflow_config_empty_dict_clears_slot(client):  # noqa: ARG001
    await set_workflow_config("tts", {"enabled": True})
    await set_workflow_config("cg", {"style": "anime"})

    await set_workflow_config("tts", {})
    assert (await get_workflow_config("tts")) == {}
    assert (await get_workflow_config("cg")) == {"style": "anime"}
