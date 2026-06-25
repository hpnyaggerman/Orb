"""Unit tests for the image_gen workflow's pure logic and ComfyUI client.

Covers config normalization, prompt assembly, scene rendering, the seed-encoding
round-trip the rehydrate path depends on, sentinel graph injection against the
real packaged template, and the ComfyUI client's failure-to-ComfyError mapping --
all with no DB and a mocked HTTP transport.
"""

from __future__ import annotations

import httpx
import pytest

from backend.workflows.image_gen import comfy, prompt_assembly
from backend.workflows.image_gen.comfy import ComfyError

# --- prompt assembly ---------------------------------------------------------


def test_normalize_config_fills_and_coerces():
    cfg = prompt_assembly.normalize_config({"cfg": "7", "steps": "30", "seed": "5"})
    assert cfg["cfg"] == 7.0
    assert cfg["steps"] == 30
    assert cfg["seed"] == 5
    assert cfg["quality_tags"] == prompt_assembly.CONFIG_DEFAULTS["quality_tags"]
    assert cfg["persona_prompts"] == {}


def test_normalize_config_rejects_non_dict_persona_prompts():
    cfg = prompt_assembly.normalize_config({"persona_prompts": "oops"})
    assert cfg["persona_prompts"] == {}


def test_assemble_positive_prepends_tags_in_order():
    # Mechanical prefix order: quality, then artist, then style, then the model's
    # composed tags.
    cfg = {"artist_tags": "by artist", "style_tags": "anime", "quality_tags": "best quality"}
    assert prompt_assembly.assemble_positive("a knight", cfg) == "best quality, by artist, anime, a knight"


def test_assemble_positive_skips_empty_tags_and_trims():
    cfg = {"artist_tags": "", "style_tags": "  ", "quality_tags": "best quality,"}
    assert prompt_assembly.assemble_positive("a knight", cfg) == "best quality, a knight"


def test_resolve_negative_falls_back_to_default_when_empty():
    assert prompt_assembly.resolve_negative({}) == prompt_assembly.DEFAULT_NEGATIVE
    assert prompt_assembly.resolve_negative({"negative_prompt": "  "}) == prompt_assembly.DEFAULT_NEGATIVE


def test_resolve_negative_honors_override():
    assert prompt_assembly.resolve_negative({"negative_prompt": "lowres"}) == "lowres"


def test_resolve_negative_sanitizes_stray_commas():
    assert prompt_assembly.resolve_negative({"negative_prompt": "lowres,, bad hands,"}) == "lowres, bad hands"


def test_resolve_quality_falls_back_to_default_when_empty():
    assert prompt_assembly.resolve_quality({}) == prompt_assembly.DEFAULT_QUALITY_TAGS


def test_resolve_quality_honors_override():
    assert prompt_assembly.resolve_quality({"quality_tags": "best quality"}) == "best quality"


def test_assemble_positive_uses_default_quality_when_empty():
    assert prompt_assembly.assemble_positive("a knight", {}) == prompt_assembly.DEFAULT_QUALITY_TAGS + ", a knight"


def test_assemble_positive_sanitizes_stray_commas():
    # Leading, trailing, doubled, and comma-only sections never produce a double
    # comma or an empty segment in the joined prompt.
    cfg = {"quality_tags": "best quality,", "style_tags": "anime,,", "artist_tags": ","}
    assert prompt_assembly.assemble_positive(", a knight ,", cfg) == "best quality, anime, a knight"


def test_build_test_positive_orders_pieces_and_appends_scene():
    cfg = {"quality_tags": "best quality", "style_tags": "anime", "artist_tags": "by x"}
    out = prompt_assembly.build_test_positive(cfg, "a knight", "a mage")
    assert out == "best quality, by x, anime, a knight, a mage, " + prompt_assembly.TEST_SCENE


def test_build_test_positive_without_character_or_persona():
    # Nothing about the character or persona is assumed when both are unset: their
    # fragments drop out and the neutral scene (with the default quality) stands.
    out = prompt_assembly.build_test_positive({}, "", "")
    assert out == prompt_assembly.DEFAULT_QUALITY_TAGS + ", " + prompt_assembly.TEST_SCENE


def test_resolve_guideline_falls_back_to_default_when_empty():
    assert prompt_assembly.resolve_guideline({}) == prompt_assembly.DEFAULT_GUIDELINE
    assert prompt_assembly.resolve_guideline({"prompt_guideline": "   "}) == prompt_assembly.DEFAULT_GUIDELINE


def test_resolve_guideline_honors_override():
    assert prompt_assembly.resolve_guideline({"prompt_guideline": "tags only"}) == "tags only"


def test_config_has_no_global_default_prompts():
    # A global default character/persona prompt is meaningless across distinct
    # characters, so neither exists.
    assert "default_character_prompt" not in prompt_assembly.CONFIG_DEFAULTS
    assert "default_persona_prompt" not in prompt_assembly.CONFIG_DEFAULTS


def test_placeholdered_fields_default_to_empty():
    # Fields with a baked default store empty so the default applies only when
    # the user leaves them blank.
    for key in ("prompt_guideline", "quality_tags", "negative_prompt"):
        assert prompt_assembly.CONFIG_DEFAULTS[key] == ""


def test_compute_seed_fixed_is_reduced_and_round_trips():
    # A fixed seed in the upper half of the backend's range is reduced the same
    # way reroll_gen reduces it, so first render and rehydrate agree.
    big = 2**63 + 17
    seed = prompt_assembly.compute_seed({"seed": big})
    assert 0 <= seed < 2**63
    assert seed == big % (2**63)
    assert int(format(seed, "x"), 16) == seed


def test_compute_seed_negative_is_random_in_range():
    seeds = {prompt_assembly.compute_seed({"seed": -1}) for _ in range(20)}
    assert all(0 <= s < 2**63 for s in seeds)
    assert len(seeds) > 1


def test_build_generation_metadata_excludes_seed():
    params = {"cfg": 5.0, "steps": 40, "width": 1536, "height": 1152, "seed": 99}
    md = prompt_assembly.build_generation_metadata("pos", "neg", params, "http://comfy")
    assert md["positive"] == "pos"
    assert md["negative"] == "neg"
    assert md["comfy_url"] == "http://comfy"
    assert "seed" not in md


def test_render_scene_block_formats_outfit_delta():
    scene = {
        "characters_present": ["Mira"],
        "outfits": [{"character": "Mira", "added_articles": ["red cloak"], "removed_default_articles": ["boots"]}],
        "anchors": ["fireplace"],
        "positions": [{"character": "Mira", "relative_to_anchor": "beside the fireplace"}],
        "poses": [{"character": "Mira", "pose": "kneeling"}],
        "actions": [{"character": "Mira", "action": "warming her hands"}],
    }
    text = prompt_assembly.render_scene_block(scene)
    assert "Characters present: Mira" in text
    assert "wearing red cloak" in text
    assert "without boots" in text
    assert "fireplace" in text
    assert "kneeling" in text


def test_render_scene_block_tolerates_garbage():
    assert prompt_assembly.render_scene_block(None) == ""
    assert prompt_assembly.render_scene_block({"outfits": ["not a dict"]}) == ""


# --- direction-note weave into the two pass instructions ---------------------

_NOTES_BLOCK = "**Direction Notes**\n- (Characterization, turn 2) She lost her left arm."


def test_analyze_instruction_omits_direction_notes_when_empty():
    # The new parameter defaults to no block, leaving the instruction unchanged.
    out = prompt_assembly.analyze_instruction("a knight")
    assert "Lasting developments" not in out
    assert out == prompt_assembly.analyze_instruction("a knight", "")


def test_analyze_instruction_appends_direction_notes_after_char_block():
    out = prompt_assembly.analyze_instruction("a knight", _NOTES_BLOCK)
    assert _NOTES_BLOCK in out
    # Notes trail the character default; the caller then appends the moment after the
    # whole instruction, so the moment still lands last.
    assert out.index("a knight") < out.index(_NOTES_BLOCK)


def test_compose_instruction_omits_direction_notes_when_empty():
    out = prompt_assembly.compose_instruction("guide", "a knight", "a mage")
    assert "Lasting developments" not in out
    assert out == prompt_assembly.compose_instruction("guide", "a knight", "a mage", "")


def test_compose_instruction_keeps_notes_before_final_directive():
    out = prompt_assembly.compose_instruction("guide", "a knight", "a mage", _NOTES_BLOCK)
    assert _NOTES_BLOCK in out
    # The closing compose_image_prompt directive stays last in the framing, so the scene
    # the caller appends as the next message still lands last overall.
    assert out.index(_NOTES_BLOCK) < out.index("compose_image_prompt")


# --- sentinel injection ------------------------------------------------------


def test_inject_graph_fills_real_template_without_mutating_it():
    template = comfy.load_template()
    graph = comfy.inject_graph(
        template,
        {"positive": "POS", "negative": "NEG", "seed": 123, "cfg": 5.0, "steps": 40, "width": 1536, "height": 1152},
    )
    assert graph["11"]["inputs"]["text"] == "POS"
    assert graph["12"]["inputs"]["text"] == "NEG"
    assert graph["19"]["inputs"]["seed"] == 123
    assert graph["75"]["inputs"]["seed"] == 123
    assert graph["19"]["inputs"]["cfg"] == 5.0
    assert graph["19"]["inputs"]["steps"] == 40
    assert graph["102"]["inputs"]["width"] == 1536
    # The shared template is untouched so concurrent renders cannot collide.
    assert template["11"]["inputs"]["text"] == "{{positive}}"


def test_inject_graph_coerces_numeric_types():
    template = {"a": {"inputs": {"text": "{{positive}}", "cfg": "{{cfg}}", "steps": "{{steps}}"}}}
    graph = comfy.inject_graph(template, {"positive": "x", "cfg": 6, "steps": 25})
    assert isinstance(graph["a"]["inputs"]["cfg"], float)
    assert isinstance(graph["a"]["inputs"]["steps"], int)


def test_inject_graph_missing_positive_raises():
    template = {"a": {"inputs": {"text": "{{negative}}"}}}
    with pytest.raises(ComfyError):
        comfy.inject_graph(template, {"negative": "x"})


def test_inject_graph_absent_optional_sentinel_is_skipped():
    template = {"a": {"inputs": {"text": "{{positive}}"}}}
    graph = comfy.inject_graph(template, {"positive": "only"})
    assert graph["a"]["inputs"]["text"] == "only"


# --- ComfyUI client error mapping --------------------------------------------

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_MIN_GRAPH = {"101": {"class_type": "SaveImage", "inputs": {}}}


def _use_handler(monkeypatch, handler):
    def factory(*args, **kwargs):
        return _REAL_ASYNC_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _ok_history():
    return {
        "p1": {
            "status": {"status_str": "success"},
            "outputs": {"101": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}},
        }
    }


async def test_generate_image_happy_path(monkeypatch):
    def handler(req):
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        if req.url.path == "/history/p1":
            return httpx.Response(200, json=_ok_history())
        if req.url.path == "/view":
            return httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png"})
        return httpx.Response(404)

    _use_handler(monkeypatch, handler)
    data, mime = await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=5)
    assert data == b"PNGDATA"
    assert mime == "image/png"


async def test_generate_image_connect_error(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("refused")

    _use_handler(monkeypatch, handler)
    with pytest.raises(ComfyError):
        await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=5)


async def test_generate_image_http_500(monkeypatch):
    def handler(req):
        return httpx.Response(500)

    _use_handler(monkeypatch, handler)
    with pytest.raises(ComfyError):
        await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=5)


async def test_generate_image_missing_prompt_id(monkeypatch):
    def handler(req):
        return httpx.Response(200, json={})

    _use_handler(monkeypatch, handler)
    with pytest.raises(ComfyError):
        await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=5)


async def test_generate_image_node_error(monkeypatch):
    def handler(req):
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        return httpx.Response(200, json={"p1": {"status": {"status_str": "error"}, "outputs": {}}})

    _use_handler(monkeypatch, handler)
    with pytest.raises(ComfyError):
        await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=5)


async def test_generate_image_no_images(monkeypatch):
    def handler(req):
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        return httpx.Response(200, json={"p1": {"status": {"status_str": "success"}, "outputs": {"101": {"images": []}}}})

    _use_handler(monkeypatch, handler)
    with pytest.raises(ComfyError):
        await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=5)


async def test_generate_image_empty_bytes(monkeypatch):
    def handler(req):
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        if req.url.path == "/history/p1":
            return httpx.Response(200, json=_ok_history())
        return httpx.Response(200, content=b"")

    _use_handler(monkeypatch, handler)
    with pytest.raises(ComfyError):
        await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=5)


async def test_generate_image_timeout(monkeypatch):
    def handler(req):
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        # The run never appears in history, so the poll loop exhausts its deadline.
        return httpx.Response(200, json={})

    _use_handler(monkeypatch, handler)
    with pytest.raises(ComfyError):
        await comfy.generate_image(_MIN_GRAPH, base_url="http://comfy", timeout=0.05, poll_interval=0.01)
