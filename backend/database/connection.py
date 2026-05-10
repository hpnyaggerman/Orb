from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "app.db")


@asynccontextmanager
async def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()


def _build_set_clause(
    allowed: list[str], data: dict, json_fields: frozenset[str] | set[str] = frozenset()
) -> tuple[list[str], list]:
    """Build the SET clause lists for a parameterised UPDATE query.

    Returns (sets, vals) where sets is a list of 'col = ?' strings and vals
    holds the corresponding values. Columns in json_fields are JSON-serialised.
    """
    sets: list[str] = []
    vals: list = []
    for k in allowed:
        if k in data:
            sets.append(f"{k} = ?")
            vals.append(json.dumps(data[k]) if k in json_fields else data[k])
    return sets, vals
