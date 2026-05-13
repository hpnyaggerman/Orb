"""Workflow-scoped attachment writes.

Existing attachment helpers (`_attach_attachments`, `get_attachments_for_message`)
remain in `queries/messages.py` for now -- relocating them is a separate change.

`add_workflow_attachment` validates that `source` starts with `"workflow:"`
and that `workflow_id` is non-empty, so it cannot impersonate user uploads or
write generic message rows. Empty-bytes attachments are rejected after
path-to-bytes normalization.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from ..connection import get_db


async def add_workflow_attachment(message_id: int, attachment: dict) -> int:
    """Insert a workflow-owned attachment row.

    attachment dict shape:
      filename: str (required)
      mime:     str (required)
      data:     bytes XOR path: str (required; exactly one)
      source:   str starting with "workflow:" (required)
      workflow_id: str non-empty (required)
      parent_attachment_id: int or None (optional; default NULL)
      annotation: str or None (optional; default NULL)

    The "workflow:" prefix + non-empty workflow_id are enforced so callers
    cannot impersonate user uploads or write generic message rows. Path-shaped
    entries are read into bytes before the empty-bytes check, so a zero-byte
    file on disk fails the same way as an inline `data=b""`.

    Raises:
      ValueError -- bad source, empty workflow_id, both-or-neither data/path,
                    wrong types, empty bytes after path-to-bytes normalization.
      OSError    -- path read failure (caller decides whether to surface).
      LookupError -- message_id does not exist.
    """
    source = attachment.get("source")
    if not isinstance(source, str) or not source.startswith("workflow:"):
        raise ValueError(f"source must start with 'workflow:'; got {source!r}")

    workflow_id = attachment.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise ValueError(f"workflow_id must be a non-empty string; got {workflow_id!r}")

    has_data = "data" in attachment
    has_path = "path" in attachment
    if has_data == has_path:
        raise ValueError("attachment must have exactly one of 'data' or 'path'")

    if has_path:
        path = attachment["path"]
        if not isinstance(path, str):
            raise ValueError(f"path must be a string; got {type(path).__name__}")
        with open(path, "rb") as f:
            data = f.read()
    else:
        raw = attachment["data"]
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError(f"data must be bytes; got {type(raw).__name__}")
        data = bytes(raw)

    if not data:
        raise ValueError("attachment data is empty after path-to-bytes normalization")

    filename = attachment.get("filename")
    if not isinstance(filename, str):
        raise ValueError(f"filename must be a string; got {type(filename).__name__}")

    mime = attachment.get("mime")
    if not isinstance(mime, str):
        raise ValueError(f"mime must be a string; got {type(mime).__name__}")

    parent_attachment_id = attachment.get("parent_attachment_id")
    annotation = attachment.get("annotation")

    data_b64 = base64.b64encode(data).decode("ascii")
    size = len(data)

    async with get_db() as db:
        rows = list(await db.execute_fetchall("SELECT id FROM messages WHERE id = ?", (message_id,)))
        if not rows:
            raise LookupError(f"message_id {message_id!r} does not exist")

        now = datetime.now(timezone.utc).isoformat()
        cur = await db.execute(
            """INSERT INTO message_attachments
               (message_id, mime_type, data_b64, filename, size, created_at,
                source, workflow_id, parent_attachment_id, annotation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                mime,
                data_b64,
                filename,
                size,
                now,
                source,
                workflow_id,
                parent_attachment_id,
                annotation,
            ),
        )
        await db.commit()
        att_id = cur.lastrowid
        assert att_id is not None
        return att_id
