"""Mood-fragment and interactive-fragment CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core import match_folded
from ...database import (
    create_interactive_fragment,
    create_mood_fragment,
    delete_interactive_fragment,
    delete_mood_fragment,
    get_interactive_fragments,
    get_mood_fragments,
    update_interactive_fragment,
    update_mood_fragment,
)
from ..schemas import (
    InteractiveFragmentCreate,
    InteractiveFragmentUpdate,
    MoodFragmentCreate,
    MoodFragmentUpdate,
)

router = APIRouter()


def _taken_by(new_id: str, rows) -> str | None:
    """The existing id that *new_id* would be read as, or ``None`` when it is free.

    The model's reply is matched to fragment ids ignoring case and separators,
    so an id that differs from an existing one only that way could never be
    told apart from it and is refused at creation instead.
    """
    return match_folded(new_id, [row["id"] for row in rows])


def _taken_detail(kind: str, new_id: str, taken_by: str) -> str:
    if taken_by == new_id:
        return f"{kind} with this ID already exists"
    return (
        f"{kind} ID '{new_id}' would be read as the existing fragment '{taken_by}': "
        "IDs that differ only by case or separators are the same field"
    )


# Mood Fragments ──


@router.get("/api/fragments")
async def api_list_mood_fragments():
    return await get_mood_fragments()


@router.post("/api/fragments")
async def api_create_mood_fragment(data: MoodFragmentCreate):
    taken_by = _taken_by(data.id, await get_mood_fragments())
    if taken_by is not None:
        raise HTTPException(status_code=400, detail=_taken_detail("Mood fragment", data.id, taken_by))
    return await create_mood_fragment(data.model_dump())


@router.put("/api/fragments/{fid}")
async def api_update_mood_fragment(fid: str, data: MoodFragmentUpdate):
    result = await update_mood_fragment(fid, data.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail="Mood fragment not found")
    return result


@router.delete("/api/fragments/{fid}")
async def api_delete_mood_fragment(fid: str):
    if not await delete_mood_fragment(fid):
        raise HTTPException(status_code=404, detail="Mood fragment not found or is built-in")
    return {"ok": True}


# Interactive Fragments ──


@router.get("/api/interactive-fragments")
async def api_list_interactive_fragments():
    return await get_interactive_fragments()


def _missing_profile(e: Exception) -> HTTPException | None:
    """The 404 for a ``model_config_id`` naming no profile, or ``None`` for any other failure."""
    if "FOREIGN KEY constraint failed" in str(e):
        return HTTPException(status_code=404, detail="Profile not found")
    return None


@router.post("/api/interactive-fragments")
async def api_create_interactive_fragment(data: InteractiveFragmentCreate):
    taken_by = _taken_by(data.id, await get_interactive_fragments())
    if taken_by is not None:
        raise HTTPException(status_code=400, detail=_taken_detail("Interactive fragment", data.id, taken_by))
    try:
        result = await create_interactive_fragment(data.model_dump())
    except Exception as e:
        if (missing := _missing_profile(e)) is not None:
            raise missing from e
        raise
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create interactive fragment")
    return result


@router.put("/api/interactive-fragments/{fid}")
async def api_update_interactive_fragment(fid: str, data: InteractiveFragmentUpdate):
    payload = data.model_dump(exclude_none=True)
    if "model_config_id" in data.model_fields_set:
        payload["model_config_id"] = data.model_config_id
    try:
        result = await update_interactive_fragment(fid, payload)
    except Exception as e:
        if (missing := _missing_profile(e)) is not None:
            raise missing from e
        raise
    if not result:
        raise HTTPException(status_code=404, detail="Interactive fragment not found")
    return result


@router.delete("/api/interactive-fragments/{fid}")
async def api_delete_interactive_fragment(fid: str):
    if not await delete_interactive_fragment(fid):
        raise HTTPException(status_code=404, detail="Interactive fragment not found")
    return {"ok": True}
