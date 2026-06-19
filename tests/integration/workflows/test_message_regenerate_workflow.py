"""End-to-end coverage for message-level regenerate's workflow integration.

Baseline counterpart to the magic_rewrite workflow test: a plain regenerate runs
the full pipeline and persists a new sibling, so the post-pipeline draft
replacement, artifact, and per-message state land on the new sibling while the
original reply and its attachments are preserved.
"""

from __future__ import annotations

from backend.database import (
    get_conversation_logs,
    get_message_by_id,
    get_messages,
    get_workflow_attachments_for_message,
    get_workflow_message_state,
)
from backend.workflows import set_workflow_config

from ._fixtures import make_workflow, register_for_test

_WID = "regen_probe"
_REWRITTEN = "<<probe-rewrote-this-draft>>"


def _probe_workflow():
    """Workflow whose post-pipeline hook exercises all three persisted effects:
    a draft replacement, an attached artifact, and per-message state."""

    async def post_pipeline(ctx):
        yield {"type": "draft_replaced", "draft": _REWRITTEN}
        yield {
            "type": "attach_artifact",
            "attachment": {
                "filename": "probe.txt",
                "mime": "text/plain",
                "data": b"probe-artifact",
                "source": f"workflow:{_WID}",
                "workflow_id": _WID,
            },
        }
        yield {"type": "set_message_state", "state": {"touched": True}}

    async def regenerate(ctx, body):
        return []

    async def reroll_gen(ctx, params, seed):
        return b"unused"

    return make_workflow(
        _WID,
        post_pipeline=post_pipeline,
        regenerate=regenerate,
        reroll_gen=reroll_gen,
        produces_artifacts=True,
    )


async def _seed_reply(client, llm_mock) -> tuple[str, int]:
    """Create a conversation and one assistant reply with no probe workflow
    active, returning the conversation id and the original reply's id."""
    card = await client.post(
        "/api/characters",
        json={"name": "Aria", "description": "An elf ranger.", "first_mes": "The woods are quiet."},
    )
    assert card.status_code == 200
    conv = await client.post("/api/conversations", json={"character_card_id": card.json()["id"]})
    assert conv.status_code == 200
    cid = conv.json()["id"]

    resp = await client.put(
        "/api/settings",
        json={"model_name": "writer-model", "enable_agent": True, "enabled_tools": {"direct_scene": True}},
    )
    assert resp.status_code == 200
    # The format normalizer would otherwise rewrite the draft before the probe
    # runs; disable it so the seeded and rewritten contents are exact.
    await set_workflow_config("format_consistency", {"enabled": False})

    llm_mock.enqueue_writer("The original reply.")
    send = await client.post(f"/api/conversations/{cid}/send", json={"content": "Tell me a story.", "attachments": []})
    assert send.status_code == 200
    _ = send.text

    original = [m for m in await get_messages(cid) if m["role"] == "assistant"][-1]
    return cid, original["id"]


async def test_regenerate_runs_post_pipeline_on_a_new_sibling(client, llm_mock):
    cid, original_id = await _seed_reply(client, llm_mock)
    original = await get_message_by_id(original_id)
    assert original is not None

    with register_for_test(_probe_workflow()):
        llm_mock.enqueue_writer("A fresh draft the probe will replace.")
        logs_before = len(await get_conversation_logs(cid))
        resp = await client.post(f"/api/conversations/{cid}/messages/{original_id}/regenerate", json={})
        assert resp.status_code == 200
        _ = resp.text
        logs_after = await get_conversation_logs(cid)

    # The original is untouched and keeps no probe artifact.
    original_now = await get_message_by_id(original_id)
    assert original_now is not None
    assert original_now["content"] == "The original reply."
    assert not [a for a in await get_workflow_attachments_for_message(original_id) if a["workflow_id"] == _WID]

    # A new sibling carries the rewrite at the same branch point.
    sibling = [m for m in await get_messages(cid) if m["role"] == "assistant"][-1]
    assert sibling["id"] != original_id
    sibling_row = await get_message_by_id(sibling["id"])
    assert sibling_row is not None
    assert sibling_row["turn_index"] == original["turn_index"]
    assert sibling_row["parent_id"] == original["parent_id"]
    assert sibling_row["content"] == _REWRITTEN

    # The artifact and per-message state land on the sibling.
    atts = [a for a in await get_workflow_attachments_for_message(sibling["id"]) if a["workflow_id"] == _WID]
    assert len(atts) == 1
    assert await get_workflow_message_state(sibling["id"], _WID) == {"touched": True}

    # The turn logged exactly once.
    assert len(logs_after) == logs_before + 1
