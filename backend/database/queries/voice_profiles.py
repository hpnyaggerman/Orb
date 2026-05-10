from __future__ import annotations

from ..connection import get_db


async def get_voice_profile(character_card_id: str) -> dict | None:
    """Return the voice profile for a character, or None."""
    async with get_db() as db:
        row = await db.execute(
            "SELECT * FROM voice_profiles WHERE character_card_id = ?",
            (character_card_id,),
        )
        r = await row.fetchone()
        return dict(r) if r else None


async def upsert_voice_profile(character_card_id: str, data: dict) -> dict:
    """Create or update a voice profile for a character.

    Accepts a subset of voice_profiles columns. Missing fields keep their
    current or default values.
    """
    async with get_db() as db:
        allowed = {
            "backend",
            "voice_id",
            "language",
            "rate",
            "pitch",
            "enabled",
            "endpoint_id",
            "api_url",
            "api_key",
            "model",
        }
        updates = {k: v for k, v in data.items() if k in allowed}

        # Check if profile exists
        row = await db.execute(
            "SELECT id FROM voice_profiles WHERE character_card_id = ?",
            (character_card_id,),
        )
        existing = await row.fetchone()

        if existing:
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                vals = list(updates.values()) + [character_card_id]
                await db.execute(
                    f"UPDATE voice_profiles SET {sets}, updated_at = datetime('now') WHERE character_card_id = ?",
                    vals,
                )
                await db.commit()
        else:
            cols = ["character_card_id"] + list(updates.keys())
            placeholders = ", ".join("?" * len(cols))
            vals = [character_card_id] + list(updates.values())
            await db.execute(
                f"INSERT INTO voice_profiles ({', '.join(cols)}) VALUES ({placeholders})",
                vals,
            )
            await db.commit()

    profile = await get_voice_profile(character_card_id)
    if profile is None:
        raise RuntimeError("Failed to load saved voice profile")
    return profile
