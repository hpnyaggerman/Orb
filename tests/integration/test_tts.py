"""Integration tests for TTS API endpoints and voice profile CRUD."""

from __future__ import annotations

import edge_tts

from backend.tts.base import SynthesisResult


FAKE_EDGE_VOICES = [
    {
        "ShortName": "en-US-JennyNeural",
        "FriendlyName": "Microsoft Jenny Online",
        "Locale": "en-US",
        "Gender": "Female",
    },
    {
        "ShortName": "en-GB-RyanNeural",
        "FriendlyName": "Microsoft Ryan Online",
        "Locale": "en-GB",
        "Gender": "Male",
    },
    {
        "ShortName": "de-DE-KatjaNeural",
        "FriendlyName": "Microsoft Katja Online",
        "Locale": "de-DE",
        "Gender": "Female",
    },
]


async def _fake_edge_voices():
    return FAKE_EDGE_VOICES


async def test_list_backends(client):
    resp = await client.get("/api/tts/backends")
    assert resp.status_code == 200
    backends = resp.json()
    assert isinstance(backends, list)
    assert any(b["id"] == "edge" for b in backends)
    for backend in backends:
        assert "id" in backend
        assert "name" in backend


async def test_list_voices_default(client, monkeypatch):
    monkeypatch.setattr(edge_tts, "list_voices", _fake_edge_voices)
    resp = await client.get("/api/tts/voices")
    assert resp.status_code == 200
    voices = resp.json()
    assert isinstance(voices, list)
    assert len(voices) > 0
    # Should have id and name fields
    assert "id" in voices[0]


async def test_list_voices_by_language(client, monkeypatch):
    monkeypatch.setattr(edge_tts, "list_voices", _fake_edge_voices)
    resp = await client.get("/api/tts/voices?backend=edge&language=en")
    assert resp.status_code == 200
    voices = resp.json()
    assert len(voices) > 0
    for v in voices:
        assert v["id"].startswith("en-")


async def test_voice_profile_crud(client):
    # Create a character first
    char = await client.post("/api/characters", json={"name": "Voice Test Char"})
    assert char.status_code == 200
    char_id = char.json()["id"]

    # GET — no profile yet
    resp = await client.get(f"/api/characters/{char_id}/voice-profile")
    assert resp.status_code == 200
    profile = resp.json()
    assert profile.get("enabled", 0) == 0 or "backend" not in profile

    # PUT — create profile
    resp = await client.put(
        f"/api/characters/{char_id}/voice-profile",
        json={
            "backend": "edge",
            "voice_id": "en-US-JennyNeural",
            "language": "en-US",
            "rate": 1.0,
            "pitch": 1.0,
            "enabled": 1,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["backend"] == "edge"
    assert data["voice_id"] == "en-US-JennyNeural"
    assert data["enabled"] == 1

    # GET — profile exists now
    resp = await client.get(f"/api/characters/{char_id}/voice-profile")
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["backend"] == "edge"
    assert profile["voice_id"] == "en-US-JennyNeural"

    # PUT — update profile
    resp = await client.put(
        f"/api/characters/{char_id}/voice-profile",
        json={
            "backend": "edge",
            "voice_id": "en-US-AriaNeural",
            "language": "en-US",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["voice_id"] == "en-US-AriaNeural"

    # GET — verify update
    resp = await client.get(f"/api/characters/{char_id}/voice-profile")
    assert resp.json()["voice_id"] == "en-US-AriaNeural"


async def test_voice_profile_nonexistent_character(client):
    resp = await client.get("/api/characters/nonexistent-id/voice-profile")
    assert resp.status_code == 200  # Returns empty profile, not 404

    resp = await client.put(
        "/api/characters/nonexistent-id/voice-profile",
        json={"backend": "edge", "voice_id": "en-US-JennyNeural"},
    )
    assert resp.status_code in (404, 400)  # Character doesn't exist


class FakeAdapter:
    def __init__(self, content_type: str = "audio/mpeg"):
        self.content_type = content_type
        self.calls = []
        self.supports_emotion_tags = False

    async def synthesize(self, **kwargs):
        self.calls.append(kwargs)
        return SynthesisResult(
            audio_bytes=b"fake-audio",
            content_type=self.content_type,
        )

    async def list_voices(self, language: str = ""):
        return []

    @property
    def backend_name(self) -> str:
        return "Fake"


async def _create_tts_conversation(client, *, first_mes: str = "Hello there."):
    char_resp = await client.post(
        "/api/characters",
        json={"name": "Speak Test Char", "first_mes": first_mes},
    )
    assert char_resp.status_code == 200
    char_id = char_resp.json()["id"]

    conv_resp = await client.post(
        "/api/conversations",
        json={"character_card_id": char_id},
    )
    assert conv_resp.status_code == 200
    cid = conv_resp.json()["id"]

    messages_resp = await client.get(f"/api/conversations/{cid}/messages")
    assert messages_resp.status_code == 200
    msg_id = messages_resp.json()[0]["id"]
    return char_id, cid, msg_id


async def test_speak_message_rejects_non_assistant_message(client, db):
    char_id, cid, assistant_id = await _create_tts_conversation(client)
    async with db.execute(
        "INSERT INTO messages (conversation_id, role, content, turn_index, parent_id, created_at) VALUES (?, 'user', 'Hi', 1, ?, datetime('now'))",
        (cid, assistant_id),
    ) as cur:
        user_msg_id = cur.lastrowid
    await db.commit()

    await client.put("/api/settings", json={"tts_enabled": 1})
    resp = await client.put(
        f"/api/characters/{char_id}/voice-profile",
        json={
            "backend": "edge",
            "voice_id": "en-US-JennyNeural",
            "enabled": 1,
        },
    )
    assert resp.status_code == 200

    resp = await client.post(f"/api/conversations/{cid}/messages/{user_msg_id}/speak")
    assert resp.status_code == 400
    assert "assistant" in resp.text


async def test_speak_message_rejects_disabled_voice_profile(client):
    char_id, cid, msg_id = await _create_tts_conversation(client)
    await client.put("/api/settings", json={"tts_enabled": 1})
    resp = await client.put(
        f"/api/characters/{char_id}/voice-profile",
        json={
            "backend": "edge",
            "voice_id": "en-US-JennyNeural",
            "enabled": 0,
        },
    )
    assert resp.status_code == 200

    resp = await client.post(f"/api/conversations/{cid}/messages/{msg_id}/speak")
    assert resp.status_code == 400
    assert "not enabled" in resp.text


async def test_speak_message_synthesizes_and_reuses_cache(client, monkeypatch, tmp_path):
    import backend.main as main
    import backend.tts.cache as tts_cache

    char_id, cid, msg_id = await _create_tts_conversation(client)
    adapter = FakeAdapter(content_type="audio/wav")

    monkeypatch.setattr(tts_cache, "TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(main, "get_adapter", lambda backend: adapter)

    await client.put("/api/settings", json={"tts_enabled": 1})
    resp = await client.put(
        f"/api/characters/{char_id}/voice-profile",
        json={
            "backend": "kokoro",
            "voice_id": "af_heart",
            "language": "en-US",
            "enabled": 1,
        },
    )
    assert resp.status_code == 200

    first = await client.post(f"/api/conversations/{cid}/messages/{msg_id}/speak")
    assert first.status_code == 200
    assert first.content == b"fake-audio"
    assert first.headers["content-type"] == "audio/wav"
    assert len(adapter.calls) == 1

    second = await client.post(f"/api/conversations/{cid}/messages/{msg_id}/speak")
    assert second.status_code == 200
    assert second.content == b"fake-audio"
    assert second.headers["content-type"] == "audio/wav"
    assert len(adapter.calls) == 1


async def test_voice_profile_update_clears_all_cached_audio_extensions(client, monkeypatch, tmp_path):
    import backend.tts.cache as tts_cache

    char_id, cid, _msg_id = await _create_tts_conversation(client)
    cache_dir = tmp_path / cid
    cache_dir.mkdir()
    mp3_path = cache_dir / "1_old.mp3"
    wav_path = cache_dir / "1_old.wav"
    mp3_path.write_bytes(b"mp3")
    wav_path.write_bytes(b"wav")

    monkeypatch.setattr(tts_cache, "TTS_CACHE_DIR", str(tmp_path))

    resp = await client.put(
        f"/api/characters/{char_id}/voice-profile",
        json={
            "backend": "edge",
            "voice_id": "en-US-JennyNeural",
            "enabled": 1,
        },
    )
    assert resp.status_code == 200
    assert not mp3_path.exists()
    assert not wav_path.exists()


# ── Chunk metadata endpoint ──────────────────────────────────


async def _setup_tts_env(client, monkeypatch, tmp_path, *, first_mes=None):
    """Create a character, conversation, enable TTS, patch adapter + cache dir."""
    import backend.main as main
    import backend.tts.cache as tts_cache

    kwargs = {}
    if first_mes:
        kwargs["first_mes"] = first_mes
    char_id, cid, msg_id = await _create_tts_conversation(client, **kwargs)

    adapter = FakeAdapter(content_type="audio/mpeg")
    monkeypatch.setattr(tts_cache, "TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(main, "get_adapter", lambda backend: adapter)

    await client.put("/api/settings", json={"tts_enabled": 1})
    await client.put(
        f"/api/characters/{char_id}/voice-profile",
        json={
            "backend": "edge",
            "voice_id": "en-US-JennyNeural",
            "language": "en-US",
            "enabled": 1,
        },
    )
    return char_id, cid, msg_id, adapter


async def test_get_chunks_returns_chunk_metadata(client, monkeypatch, tmp_path):
    _char_id, cid, msg_id, _adapter = await _setup_tts_env(
        client,
        monkeypatch,
        tmp_path,
        first_mes='"Hello there," she said. "How are you?"',
    )

    resp = await client.get(f"/api/conversations/{cid}/messages/{msg_id}/chunks")
    assert resp.status_code == 200
    data = resp.json()
    assert "chunks" in data
    assert data["extraction_method"] == "regex"
    chunks = data["chunks"]
    assert len(chunks) == 2

    # Each chunk has required fields
    for c in chunks:
        assert "index" in c
        assert "text" in c
        assert "original_text" in c
        assert "emotion" in c
        assert "pause_before_ms" in c

    # First chunk: "Hello there,"
    assert chunks[0]["index"] == 0
    assert "Hello there" in chunks[0]["original_text"]
    assert chunks[0]["pause_before_ms"] == 0  # First chunk has no leading pause

    # Second chunk: "How are you?"
    assert chunks[1]["index"] == 1
    assert "How are you" in chunks[1]["original_text"]
    assert chunks[1]["pause_before_ms"] > 0  # Inter-dialogue pause


async def test_get_chunks_empty_no_quoted_dialogue(client, monkeypatch, tmp_path):
    _char_id, cid, msg_id, _adapter = await _setup_tts_env(
        client,
        monkeypatch,
        tmp_path,
        first_mes="*She smiles and looks away.*",
    )

    resp = await client.get(f"/api/conversations/{cid}/messages/{msg_id}/chunks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chunks"] == []


async def test_get_chunks_tts_disabled(client):
    char_id, cid, msg_id = await _create_tts_conversation(client)
    # TTS is disabled by default
    resp = await client.get(f"/api/conversations/{cid}/messages/{msg_id}/chunks")
    assert resp.status_code == 403


async def test_get_chunks_no_voice_profile(client):
    char_id, cid, msg_id = await _create_tts_conversation(client)
    await client.put("/api/settings", json={"tts_enabled": 1})
    resp = await client.get(f"/api/conversations/{cid}/messages/{msg_id}/chunks")
    assert resp.status_code == 400


async def test_get_chunks_nonexistent_message(client, monkeypatch, tmp_path):
    char_id, cid, _msg_id, _adapter = await _setup_tts_env(client, monkeypatch, tmp_path)
    resp = await client.get(f"/api/conversations/{cid}/messages/99999/chunks")
    assert resp.status_code == 404


# ── Speak-chunk endpoint ─────────────────────────────────────


async def test_speak_chunk_single(client, monkeypatch, tmp_path):
    _char_id, cid, msg_id, adapter = await _setup_tts_env(
        client,
        monkeypatch,
        tmp_path,
        first_mes='"Hello there," she said. "How are you?"',
    )

    resp = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": 0},
    )
    assert resp.status_code == 200
    assert resp.content == b"fake-audio"
    assert len(adapter.calls) == 1
    # Verify it only synthesized 1 chunk
    chunks_arg = adapter.calls[0]["chunks"]
    assert len(chunks_arg) == 1


async def test_speak_chunk_caches_per_chunk(client, monkeypatch, tmp_path):
    _char_id, cid, msg_id, adapter = await _setup_tts_env(
        client,
        monkeypatch,
        tmp_path,
        first_mes='"Hello there," she said. "How are you?"',
    )

    # Request chunk 0
    first = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": 0},
    )
    assert first.status_code == 200
    assert len(adapter.calls) == 1

    # Request chunk 0 again — should use cache
    second = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": 0},
    )
    assert second.status_code == 200
    assert len(adapter.calls) == 1  # No new call

    # Request chunk 1 — should synthesize new
    third = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": 1},
    )
    assert third.status_code == 200
    assert len(adapter.calls) == 2


async def test_speak_chunk_out_of_range(client, monkeypatch, tmp_path):
    _char_id, cid, msg_id, _adapter = await _setup_tts_env(
        client,
        monkeypatch,
        tmp_path,
        first_mes='"Hello there," she said.',
    )

    resp = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": 99},
    )
    assert resp.status_code == 400
    assert "out of range" in resp.text


async def test_speak_chunk_negative_index(client, monkeypatch, tmp_path):
    _char_id, cid, msg_id, _adapter = await _setup_tts_env(
        client,
        monkeypatch,
        tmp_path,
        first_mes='"Hello there."',
    )

    resp = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": -1},
    )
    assert resp.status_code == 400


async def test_speak_chunk_tts_disabled(client):
    char_id, cid, msg_id = await _create_tts_conversation(client)
    resp = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": 0},
    )
    assert resp.status_code == 403


async def test_speak_chunk_no_dialogue_empty_audio(client, monkeypatch, tmp_path):
    """Messages with no extractable dialogue should return 400 on speak-chunk."""
    _char_id, cid, msg_id, _adapter = await _setup_tts_env(
        client,
        monkeypatch,
        tmp_path,
        first_mes="*She looks away silently.*",
    )

    resp = await client.post(
        f"/api/conversations/{cid}/messages/{msg_id}/speak-chunk",
        json={"chunk_index": 0},
    )
    assert resp.status_code == 400  # No chunks to speak
