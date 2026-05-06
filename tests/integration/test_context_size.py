"""Test GET /api/conversations/{cid}/context-size"""


async def test_context_size_returns_breakdown(client):
    """Context size endpoint returns token estimates per component."""
    # Create a character with enough content to register in the breakdown
    await client.post(
        "/api/characters",
        json={
            "id": "test-char-ctx",
            "name": "TestChar",
            "data": {
                "spec": "chara_card_v2",
                "data": {
                    "name": "TestChar",
                    "description": "A test character with a detailed persona for context size testing. She is curious, witty, and observant. She enjoys long conversations about philosophy and technology.",
                    "personality": "Curious, witty, observant. Enjoys philosophical discussions and has a dry sense of humor.",
                    "scenario": "TestChar and the user are sitting in a quiet cafe, having a deep conversation about the nature of artificial intelligence.",
                    "first_mes": "Hello! I see you're reading about neural networks too. What brings you here?",
                },
            },
        },
    )

    # Create a conversation
    resp = await client.post(
        "/api/conversations",
        json={
            "character_card_id": "test-char-ctx",
            "character_name": "TestChar",
            "character_scenario": "TestChar and the user are sitting in a quiet cafe.",
            "first_mes": "Hello! I see you're reading about neural networks too.",
        },
    )
    assert resp.status_code == 200
    cid = resp.json()["id"]

    # Get context size
    resp = await client.get(f"/api/conversations/{cid}/context-size")
    assert resp.status_code == 200
    data = resp.json()

    # Verify structure
    assert "total_tokens_est" in data
    assert "total_chars" in data
    assert "breakdown" in data
    assert "message_count" in data
    assert data["message_count"] == 0

    # Verify breakdown components
    bd = data["breakdown"]
    expected_keys = {
        "system_prompt",
        "char_persona",
        "scenario",
        "mes_example",
        "user_persona",
        "messages",
        "post_history",
        "director_injection",
        "lorebook",
    }
    assert set(bd.keys()) == expected_keys

    # Each component has chars and tokens_est
    for _, val in bd.items():
        assert "chars" in val
        assert "tokens_est" in val
        assert isinstance(val["chars"], int)
        assert isinstance(val["tokens_est"], int)

    # Total should be positive
    assert data["total_tokens_est"] > 0
    assert data["total_chars"] > 0


async def test_context_size_404_for_missing(client):
    """Context size returns 404 for non-existent conversation."""
    resp = await client.get("/api/conversations/nonexistent/context-size")
    assert resp.status_code == 404
