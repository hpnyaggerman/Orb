from __future__ import annotations

from datetime import datetime, timezone

from ..connection import _build_set_clause, get_db


async def list_conversations() -> list[dict]:
    async with get_db() as db:
        rows = list(
            await db.execute_fetchall(
                """
            SELECT c.*,
                   (SELECT m.content FROM messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY m.id DESC LIMIT 1) AS last_message_preview,
                   (SELECT COUNT(*) FROM messages m
                    WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            ORDER BY COALESCE(c.updated_at, c.created_at) DESC
        """
            )
        )
        return [dict(r) for r in rows]


async def get_conversation(cid: str) -> dict | None:
    async with get_db() as db:
        rows = list(await db.execute_fetchall("SELECT * FROM conversations WHERE id = ?", (cid,)))
        return dict(rows[0]) if rows else None


async def create_conversation(
    cid: str,
    title: str,
    char_name: str,
    char_scenario: str,
    post_history_instructions: str = "",
    character_card_id: str | None = None,
) -> dict:
    async with get_db() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """INSERT INTO conversations
               (id, title, character_card_id, character_name, character_scenario,
                post_history_instructions, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cid,
                title,
                character_card_id,
                char_name,
                char_scenario,
                post_history_instructions,
                now,
                now,
            ),
        )
        await db.execute(
            "INSERT INTO director_state (conversation_id, active_moods, keywords) VALUES (?, '[]', '[]')",
            (cid,),
        )
        await db.commit()
        result = await get_conversation(cid)
        assert result is not None
        return result


async def delete_conversation(cid: str) -> bool:
    async with get_db() as db:
        cur = await db.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        await db.commit()
        return cur.rowcount > 0


async def touch_conversation(cid: str) -> bool:
    """Update conversation's updated_at to current time."""
    async with get_db() as db:
        now = datetime.now(timezone.utc).isoformat()
        cur = await db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
        await db.commit()
        return cur.rowcount > 0


async def update_conversation(cid: str, data: dict) -> dict | None:
    async with get_db() as db:
        allowed = ["title"]
        sets, vals = _build_set_clause(allowed, data)
        if sets:
            sets.append("updated_at = ?")
            vals.append(datetime.now(timezone.utc).isoformat())
            vals.append(cid)
            await db.execute(
                f"UPDATE conversations SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            await db.commit()
        return await get_conversation(cid)
