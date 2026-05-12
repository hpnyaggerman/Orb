"""Download character cards from external sources (CharacterHub, etc.).

Use a registry pattern so new sources can be added by calling register_source()
with a name, a browse function and a download function.
"""

from __future__ import annotations
import hashlib
import uuid
import logging
import base64
import tempfile
import os

import httpx
from fastapi import HTTPException

from . import tavern_cards

logger = logging.getLogger(__name__)

_CHUB_PAGE_SIZE = 24
_CHUB_AVATARS_BASE = "https://avatars.charhub.io/avatars"

SOURCES: dict[str, tuple] = {}


def register_source(name: str, browse_fn, download_fn):
    """Register an external source for character-card browsing and downloading."""
    SOURCES[name] = (browse_fn, download_fn)


async def browse(source: str, q: str = "", page: int = 1) -> dict:
    """Proxy external character-card search providers (avoids browser CORS)."""
    pair = SOURCES.get(source)
    if not pair:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source}")
    return await pair[0](q, page)


async def download_card(source: str, full_path: str) -> dict:
    """Download and parse a character card from an external source.

    Returns the same dict shape as the file-import endpoint so the frontend
    can feed it straight into the character editor modal.
    """
    pair = SOURCES.get(source)
    if not pair:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source}")
    card_dict, avatar_b64, avatar_mime, card_id = await pair[1](full_path)
    card_dict["id"] = card_id
    if avatar_b64:
        card_dict["avatar_b64"] = avatar_b64
        card_dict["avatar_mime"] = avatar_mime
    return card_dict


# ── CharacterHub ──────────────────────────────────────────────────────


async def _browse_characterhub(q: str, page: int) -> dict:
    params = {
        "search": q,
        "page": max(1, int(page)),
        "sort": "download_count",
        "first": _CHUB_PAGE_SIZE,
        "nsfw": "true",
        "nsfl": "true",
        "asc": "false",
        "venus": "true",
    }
    url = "https://api.chub.ai/search"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.exception("CharacterHub search failed")
        raise HTTPException(status_code=502, detail=f"CharacterHub search failed: {e}") from e

    nodes = data.get("nodes") or data.get("data", {}).get("nodes") or []
    results = []
    for n in nodes:
        full_path = n.get("fullPath") or n.get("full_path") or ""
        avatar_url = n.get("avatar_url") or n.get("max_res_url")
        if not avatar_url and full_path:
            avatar_url = f"https://avatars.charhub.io/avatars/{full_path}/avatar.webp"
        topics = n.get("topics") or n.get("tags") or []
        if not isinstance(topics, list):
            topics = []
        results.append(
            {
                "name": n.get("name", ""),
                "tagline": n.get("tagline", "") or n.get("description", "")[:140],
                "avatar_url": avatar_url,
                "full_path": full_path,
                "topics": topics,
            }
        )
    has_more = len(nodes) >= _CHUB_PAGE_SIZE
    return {"results": results, "has_more": has_more}


async def _download_characterhub_card(full_path: str):
    """Download the PNG character card from CharacterHub's CDN and parse it
    through the same tavern_cards pipeline as file import.

    Returns (card_dict, avatar_b64, avatar_mime, card_id).
    """
    if not full_path:
        raise HTTPException(status_code=400, detail="Missing full_path")
    if "/" not in full_path:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid CharacterHub full_path (expected creator/name): {full_path}",
        )
    url = f"{_CHUB_AVATARS_BASE}/{full_path}/chara_card_v2.png"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.content
    except httpx.HTTPError as e:
        logger.exception("Failed to download CharacterHub card PNG")
        raise HTTPException(status_code=502, detail=f"Failed to download card: {e}") from e

    if not content[:8].startswith(b"\x89PNG"):
        raise HTTPException(status_code=400, detail="Downloaded file does not appear to be a PNG card")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        orb_id = tavern_cards.read_orb_id(tmp_path)
        card = tavern_cards.parse(tmp_path)
        card_dict = tavern_cards.card_to_dict(card)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to parse tavern card from CharacterHub")
        raise HTTPException(status_code=400, detail=f"Failed to parse character card: {e}") from e
    finally:
        os.unlink(tmp_path)

    card_id = orb_id if orb_id else str(uuid.UUID(bytes=hashlib.sha256(content).digest()[:16], version=5))
    avatar_b64 = base64.b64encode(content).decode("ascii")
    avatar_mime = "image/png"

    return card_dict, avatar_b64, avatar_mime, card_id


register_source("characterhub", _browse_characterhub, _download_characterhub_card)
