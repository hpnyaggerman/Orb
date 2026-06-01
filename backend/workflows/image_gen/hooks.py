"""Pipeline and HTTP hooks binding image generation to the workflow framework.

Orchestration only: each function reads its context, calls the pure helpers and
the ComfyUI client, and shapes the result for the framework. Four hooks plus an
on-demand action router:

- ``post_pipeline`` -- per-turn auto-generation, gated on a per-character enable
  flag. Runs the scene analyzer and prompt composer, renders, and attaches the
  image. Any LLM-noise or ComfyUI failure degrades to no image so the turn still
  completes.
- ``regenerate`` -- full reprocess: re-run both passes against the anchor message
  and the character's current prompt/config, so an edited prompt takes effect.
- ``reroll_gen`` -- re-render the stored prompt with a supplied seed, no LLM
  passes; also backs rehydrate.
- ``on_demand`` -- a single trigger endpoint dispatched on ``body['action']`` for
  the config panel's per-character reads/writes and the test-generation preview.
"""

from __future__ import annotations

import base64
import logging

from backend.workflows.toolkit import (
    get_message_by_id,
    get_workflow_character_state,
    get_workflow_config,
    set_workflow_character_state,
)

from .comfy import ComfyError, generate_image, inject_graph, load_template
from .passes import analyze_scene, compose_prompt
from .prompt_assembly import (
    CONFIG_DEFAULTS,
    assemble_positive,
    build_generation_metadata,
    build_test_positive,
    normalize_config,
    resolve_gen_params,
    resolve_guideline,
    resolve_negative,
)

logger = logging.getLogger(__name__)

WORKFLOW_ID = "image_gen"

# Loaded once; inject_graph deep-copies it per render so concurrent turns never
# mutate the shared template.
_TEMPLATE = load_template()


def _phase(label: str) -> dict:
    return {"event": "phase_status", "data": {"channel": f"workflow:{WORKFLOW_ID}", "label": label}}


def _phase_done() -> dict:
    return {"event": "phase_status", "data": {"channel": f"workflow:{WORKFLOW_ID}", "state": "done"}}


def _resolve_prompts(ctx, cfg: dict, char_state: dict | None) -> tuple[str, str]:
    """The character and persona base prompts for the passes, or empty when none
    is configured. The persona prompt is looked up in the config's per-persona
    map by the active persona id. An empty fragment is omitted by the pass
    instructions rather than substituted with a global default."""
    char_prompt = (char_state or {}).get("prompt") or ""
    persona_id = ctx.settings.get("active_persona_id")
    persona_prompt = ""
    if persona_id is not None:
        persona_prompt = (cfg.get("persona_prompts") or {}).get(str(persona_id)) or ""
    return char_prompt, persona_prompt


def _moment(user_message: str, response: str) -> str:
    """The moment text the scene analyzer reads: the user's message plus the
    assistant response the image depicts, response last."""
    parts = []
    if user_message and user_message.strip():
        parts.append("Latest user message:\n" + user_message.strip())
    parts.append("Assistant response to depict:\n" + (response or "").strip())
    return "\n\n".join(parts)


def _cold_prefix(history) -> list[dict]:
    """A plain role/content message list from read-only history, for the off-turn
    paths that have no pipeline prefix to reuse."""
    out: list[dict] = []
    for message in history or ():
        role = message.get("role")
        content = message.get("content")
        if role and content is not None:
            out.append({"role": role, "content": content})
    return out


def _scene_ok(scene) -> bool:
    return isinstance(scene, dict) and bool(scene.get("characters_present")) and bool(scene.get("outfits"))


def _graph_values(positive: str, negative: str, params: dict) -> dict:
    return {
        "positive": positive,
        "negative": negative,
        "seed": params["seed"],
        "cfg": params["cfg"],
        "steps": params["steps"],
        "width": params["width"],
        "height": params["height"],
    }


def _attachment(img: bytes, mime: str, positive: str, negative: str, params: dict, comfy_url: str) -> dict:
    """The attachment payload for a rendered image. The seed is stored as hex so
    it round-trips through reroll_gen's int(seed, 16) decode on rehydrate."""
    return {
        "workflow_id": WORKFLOW_ID,
        "filename": "scene.png",
        "mime": mime,
        "data": img,
        "seed": format(params["seed"], "x"),
        "generation_metadata": build_generation_metadata(positive, negative, params, comfy_url),
        "consumption_metadata": None,
        "annotation": None,
    }


async def _collect(generator) -> dict:
    """Drain a pass generator and return its terminal tool arguments, ignoring the
    reasoning events (off-turn callers have no SSE stream to forward them to)."""
    args: dict = {}
    async for event in generator:
        if event.get("type") == "result":
            args = event.get("args") or {}
    return args


async def post_pipeline(ctx):
    """Generate and attach an image for a character whose image generation is
    enabled. Yields phase-status events, the two passes' reasoning, and one
    ``attach_artifact``. Every failure degrades to no image so the turn completes.
    """
    if not ctx.character_id:
        return
    char_state = await get_workflow_character_state(ctx.character_id, WORKFLOW_ID)
    if not (char_state or {}).get("enabled"):
        return
    if not (ctx.draft or "").strip():
        return
    cfg = normalize_config(await get_workflow_config(WORKFLOW_ID))
    char_prompt, persona_prompt = _resolve_prompts(ctx, cfg, char_state)
    moment = _moment(ctx.effective_msg, ctx.draft)

    yield _phase("Analyzing scene...")
    scene = None
    async for event in analyze_scene(
        client=ctx.client,
        prefix=ctx.prefix,
        char_prompt=char_prompt,
        moment=moment,
        settings=ctx.settings,
        pass_id=f"{WORKFLOW_ID}:analyze",
        kv_tracker=ctx.kv_tracker,
        enabled_tools=ctx.enabled_tools,
        schema_overrides=ctx.schema_overrides,
    ):
        if event.get("type") == "result":
            scene = event.get("args")
        else:
            yield event
    if not _scene_ok(scene):
        logger.warning("image_gen: scene analysis produced no usable scene; skipping image")
        yield _phase_done()
        return

    yield _phase("Composing prompt...")
    composed = ""
    async for event in compose_prompt(
        client=ctx.client,
        prefix=ctx.prefix,
        scene=scene,
        guideline=resolve_guideline(cfg),
        char_prompt=char_prompt,
        persona_prompt=persona_prompt,
        settings=ctx.settings,
        pass_id=f"{WORKFLOW_ID}:compose",
        kv_tracker=ctx.kv_tracker,
        enabled_tools=ctx.enabled_tools,
        schema_overrides=ctx.schema_overrides,
    ):
        if event.get("type") == "result":
            composed = (event.get("args") or {}).get("positive_prompt", "")
        else:
            yield event
    if not composed.strip():
        logger.warning("image_gen: prompt composition produced nothing; skipping image")
        yield _phase_done()
        return

    positive = assemble_positive(composed, cfg)
    negative = resolve_negative(cfg)
    params = resolve_gen_params(cfg)

    yield _phase("Rendering image...")
    try:
        graph = inject_graph(_TEMPLATE, _graph_values(positive, negative, params))
        img, mime = await generate_image(graph, base_url=cfg["comfy_url"], timeout=cfg["timeout_s"])
    except ComfyError as e:
        logger.warning("image_gen: ComfyUI render failed: %s", e)
        yield _phase_done()
        return

    att = _attachment(img, mime, positive, negative, params, cfg["comfy_url"])
    att["source"] = f"workflow:{WORKFLOW_ID}"
    yield {"type": "attach_artifact", "attachment": att}
    yield _phase_done()


async def regenerate(ctx, body):
    """Re-run both passes against the anchor message under the character's CURRENT
    prompt and config, then render. Used when the inputs changed (edited message,
    character prompt, tags) and the prompt itself should be recomputed."""
    message = await get_message_by_id(ctx.message_id)
    text = (message or {}).get("content") or ""
    if not text.strip():
        return []
    cfg = normalize_config(await get_workflow_config(WORKFLOW_ID))
    char_state = await get_workflow_character_state(ctx.character_id, WORKFLOW_ID) if ctx.character_id else None
    char_prompt, persona_prompt = _resolve_prompts(ctx, cfg, char_state)
    prefix = _cold_prefix(ctx.history)

    scene = await _collect(
        analyze_scene(
            client=ctx.client,
            prefix=prefix,
            char_prompt=char_prompt,
            moment=_moment("", text),
            settings=ctx.settings,
        )
    )
    if not _scene_ok(scene):
        return []
    composed = (
        await _collect(
            compose_prompt(
                client=ctx.client,
                prefix=prefix,
                scene=scene,
                guideline=resolve_guideline(cfg),
                char_prompt=char_prompt,
                persona_prompt=persona_prompt,
                settings=ctx.settings,
            )
        )
    ).get("positive_prompt", "")
    if not composed.strip():
        return []

    positive = assemble_positive(composed, cfg)
    negative = resolve_negative(cfg)
    params = resolve_gen_params(cfg)
    try:
        graph = inject_graph(_TEMPLATE, _graph_values(positive, negative, params))
        img, mime = await generate_image(graph, base_url=cfg["comfy_url"], timeout=cfg["timeout_s"])
    except ComfyError as e:
        logger.warning("image_gen: regenerate render failed for attachment %s: %s", ctx.attachment_id, e)
        return []
    return [_attachment(img, mime, positive, negative, params, cfg["comfy_url"])]


async def reroll_gen(ctx, params, seed):
    """Re-render the stored prompt with the supplied seed -- no LLM passes. Backs
    reroll-gen (fresh seed) and rehydrate (stored seed). The seed arrives as hex
    and is reduced the same way compute_seed reduces it, so a rehydrate of an
    original image reconstructs the identical KSampler seed. Raises on a record
    missing its prompt or on any ComfyUI failure; the route surfaces both as 500.
    """
    metadata = params if isinstance(params, dict) else {}
    positive = metadata.get("positive")
    if not positive:
        raise ValueError("generation_metadata carries no prompt to render")
    seed_int = int(seed, 16) % (2**63)
    graph = inject_graph(
        _TEMPLATE,
        {
            "positive": positive,
            "negative": metadata.get("negative", ""),
            "seed": seed_int,
            "cfg": metadata.get("cfg", CONFIG_DEFAULTS["cfg"]),
            "steps": metadata.get("steps", CONFIG_DEFAULTS["steps"]),
            "width": metadata.get("width", CONFIG_DEFAULTS["width"]),
            "height": metadata.get("height", CONFIG_DEFAULTS["height"]),
        },
    )
    cfg = normalize_config(await get_workflow_config(WORKFLOW_ID))
    base_url = metadata.get("comfy_url") or cfg["comfy_url"]
    img, _ = await generate_image(graph, base_url=base_url, timeout=cfg["timeout_s"])
    return img


async def on_demand(ctx, body):
    action = body.get("action") if isinstance(body, dict) else None
    if action == "get_char_state":
        return await _get_char_state(ctx)
    if action == "set_char_state":
        return await _set_char_state(ctx, body)
    if action == "test":
        return await _test(ctx, body)
    return {"error": f"unknown action: {action!r}"}


async def _get_char_state(ctx) -> dict:
    if not ctx.character_id:
        return {"enabled": False, "prompt": "", "character_id": None}
    state = await get_workflow_character_state(ctx.character_id, WORKFLOW_ID) or {}
    return {"enabled": bool(state.get("enabled")), "prompt": state.get("prompt") or "", "character_id": ctx.character_id}


async def _set_char_state(ctx, body) -> dict:
    if not ctx.character_id:
        return {"error": "no active character"}
    prompt = body.get("prompt")
    state = {"enabled": bool(body.get("enabled")), "prompt": prompt if isinstance(prompt, str) else ""}
    await set_workflow_character_state(ctx.character_id, WORKFLOW_ID, state)
    return {"ok": True, **state}


def _cfg_with_overrides(stored: dict, body: dict) -> dict:
    """Config for a test render: the stored slot overlaid with the panel's
    unsaved form values so the user previews exactly what they are editing."""
    overrides = body.get("config")
    if not isinstance(overrides, dict):
        overrides = {}
    return normalize_config({**(stored or {}), **overrides})


async def _render_preview(cfg: dict, positive: str) -> dict:
    negative = resolve_negative(cfg)
    params = resolve_gen_params(cfg)
    try:
        graph = inject_graph(_TEMPLATE, _graph_values(positive, negative, params))
        img, mime = await generate_image(graph, base_url=cfg["comfy_url"], timeout=cfg["timeout_s"])
    except ComfyError as e:
        return {"error": str(e)}
    return {
        "image_b64": base64.b64encode(img).decode("ascii"),
        "mime": mime,
        "positive": positive,
        "negative": negative,
        "seed": params["seed"],
    }


async def _test(ctx, body) -> dict:
    """Render a neutral preview that folds the configured quality/style/artist tags
    and the character and persona prompts into a simple baseline scene -- no LLM
    passes, nothing persisted -- so the user can confirm the prompt settings produce
    what they want. The panel's live (possibly unsaved) per-character prompt
    overrides the stored one.
    """
    cfg = _cfg_with_overrides(await get_workflow_config(WORKFLOW_ID), body)
    char_state = await get_workflow_character_state(ctx.character_id, WORKFLOW_ID) if ctx.character_id else None
    char_prompt, persona_prompt = _resolve_prompts(ctx, cfg, char_state)
    if isinstance(body.get("char_prompt"), str):
        char_prompt = body["char_prompt"]
    positive = build_test_positive(cfg, char_prompt, persona_prompt)
    return await _render_preview(cfg, positive)
