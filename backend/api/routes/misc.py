"""Miscellaneous routes: frontend shell, themes."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..deps import FRONTEND_DIR

router = APIRouter()


@router.get("/api/themes")
async def api_get_themes():
    themes_dir = os.path.join(FRONTEND_DIR, "themes")
    names = sorted(f[:-4] for f in os.listdir(themes_dir) if f.endswith(".css"))
    return {"themes": names}


@router.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
