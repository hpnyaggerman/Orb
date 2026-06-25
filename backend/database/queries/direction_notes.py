from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, cast

from ..connection import get_db
from ..models import DirectionNoteRow


async def create_direction_notes(conversation_id: str, message_id: int, notes: Sequence[Mapping[str, Any]]) -> list[int]:
    """Persist labelled notes (``interactive_fragment_id``/``interactive_fragment_label``/``content``) for one
    message; returns the new row ids. The anchor is any message on the branch: the model's
    recorded notes key to the turn's assistant reply, a user-authored note to the message the
    Notes button sat on (user or assistant)."""
    ids: list[int] = []
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        for n in notes:
            cur = await db.execute(
                "INSERT INTO direction_notes "
                "(conversation_id, message_id, interactive_fragment_id, interactive_fragment_label, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, message_id, n["interactive_fragment_id"], n["interactive_fragment_label"], n["content"], now),
            )
            row_id = cur.lastrowid
            assert row_id is not None
            ids.append(row_id)
        await db.commit()
    return ids


async def get_direction_notes_for_path(conversation_id: str, path_message_ids: Sequence[int]) -> list[DirectionNoteRow]:
    """Notes whose authoring message lies on the given active path, oldest first."""
    # An empty IN list is a SQL syntax error; the caller's path is empty only before the first reply.
    if not path_message_ids:
        return []
    placeholders = ",".join("?" for _ in path_message_ids)
    async with get_db() as db:
        rows = list(
            await db.execute_fetchall(
                f"SELECT * FROM direction_notes WHERE conversation_id = ? AND message_id IN ({placeholders}) ORDER BY id ASC",  # nosec B608 -- placeholders are a fixed-count '?' list, values parameterised
                (conversation_id, *path_message_ids),
            )
        )
        return [cast(DirectionNoteRow, dict(r)) for r in rows]


async def get_direction_notes_for_message(message_id: int) -> list[DirectionNoteRow]:
    async with get_db() as db:
        rows = list(
            await db.execute_fetchall(
                "SELECT * FROM direction_notes WHERE message_id = ? ORDER BY id ASC",
                (message_id,),
            )
        )
        return [cast(DirectionNoteRow, dict(r)) for r in rows]


async def update_direction_note(fid: int, content: str) -> DirectionNoteRow | None:
    async with get_db() as db:
        await db.execute("UPDATE direction_notes SET content = ? WHERE id = ?", (content, fid))
        await db.commit()
        rows = list(await db.execute_fetchall("SELECT * FROM direction_notes WHERE id = ?", (fid,)))
        return cast(DirectionNoteRow, dict(rows[0])) if rows else None


async def delete_direction_note(fid: int) -> bool:
    async with get_db() as db:
        cur = await db.execute("DELETE FROM direction_notes WHERE id = ?", (fid,))
        await db.commit()
        return cur.rowcount > 0
