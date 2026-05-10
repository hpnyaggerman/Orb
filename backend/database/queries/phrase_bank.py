from __future__ import annotations

import json

from ..connection import get_db


async def get_phrase_bank() -> list[list[str]]:
    """Return phrase bank as list of variant groups (list of lists)."""
    async with get_db() as db:
        rows = list(await db.execute_fetchall("SELECT variants FROM phrase_bank ORDER BY id ASC"))
        return [json.loads(r["variants"]) for r in rows]


async def get_phrase_bank_rows() -> list[dict]:
    """Return phrase bank rows with ids for UI management."""
    async with get_db() as db:
        rows = list(await db.execute_fetchall("SELECT id, variants FROM phrase_bank ORDER BY id ASC"))
        return [{"id": r["id"], "variants": json.loads(r["variants"])} for r in rows]


async def add_phrase_group(variants: list[str]) -> int:
    """Add a new phrase variant group. Returns the new row id."""
    async with get_db() as db:
        cur = await db.execute("INSERT INTO phrase_bank (variants) VALUES (?)", (json.dumps(variants),))
        await db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid


async def update_phrase_group(group_id: int, variants: list[str]) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE phrase_bank SET variants = ? WHERE id = ?",
            (json.dumps(variants), group_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_phrase_group(group_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute("DELETE FROM phrase_bank WHERE id = ?", (group_id,))
        await db.commit()
        return cur.rowcount > 0
