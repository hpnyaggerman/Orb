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
import json
import logging
from typing import AsyncIterator

from fastapi.responses import StreamingResponse

from backend.core import ChatMessage
from backend.workflows.toolkit import (
    Macros,
    build_prefix,
    get_conversation,
    get_direction_notes_for_path,
    get_message_by_id,
    get_user_personas,
    get_workflow_character_state,
    get_workflow_config,
    insert_workflow_attachment,
    render_direction_notes_block,
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


def _sse(event: dict) -> str:
    """Wire-frame an event for the off-turn production stream. The on-demand
    trigger route returns the hook's value verbatim, so the production path frames
    its own events the way the orchestrator frames the in-turn pipeline's."""
    return f"event: {event['event']}\ndata: {json.dumps(event.get('data'))}\n\n"


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


async def _resolve_direction_notes(ctx, path_messages) -> str:
    """The active-branch direction notes rendered as the block both passes receive, or ''
    when injection is off or the branch carries none.

    Gated by the global injection switch (``direction_notes_inject`` != "off"), so the image
    passes follow the same read-side setting as the director and writer rather than a switch
    of their own. Notes are fetched for *path_messages* -- the branch the depicted reply sits
    on -- and each is tagged with its authoring fragment's label and the turn it was recorded
    on, reusing the same renderer the writer's Scene Direction block uses.
    """
    if (ctx.settings.get("direction_notes_inject", "off") or "off") == "off":
        return ""
    path = [m for m in path_messages if m.get("id") is not None]
    if not path:
        return ""
    rows = await get_direction_notes_for_path(ctx.conversation_id, [m["id"] for m in path])
    if not rows:
        return ""
    turn_by_message = {m["id"]: m.get("turn_index") for m in path}
    notes = [
        {
            "interactive_fragment_label": r["interactive_fragment_label"],
            "content": r["content"],
            "turn_index": turn_by_message.get(r["message_id"]),
        }
        for r in rows
    ]
    return render_direction_notes_block(notes)


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


def _resolve_char_context(settings, card) -> tuple[str, str, str]:
    """Resolve the effective system prompt, character persona, and example messages.

    A duplicate of ``database.resolve_char_context`` (minus its card fetch -- the
    card is always supplied off-turn): the production path cannot reach the
    pipeline's prefix builder, which lives a layer above the workflow. Keep in sync
    with ``backend.database.queries.character_cards.resolve_char_context``.
    """
    shared = settings.get("shared_system_prompt", "")
    model_specific = settings.get("system_prompt", "")
    system_prompt = f"{shared}\n\n{model_specific}" if shared and model_specific else (shared or model_specific)
    char_persona, mes_example = "", ""
    if card:
        char_persona = "\n\n".join(filter(None, [card.get("description", ""), card.get("personality", "")]))
        mes_example = card.get("mes_example", "")
        card_system_prompt = card.get("system_prompt")
        if card_system_prompt and not settings.get("prevent_prompt_overrides"):
            system_prompt = card_system_prompt
    return system_prompt, char_persona, mes_example


def _resolve_persona_id(conv, card, settings):
    """Effective persona id: conversation pin -> character pin -> global active.

    A duplicate of ``pipeline.predicates.resolve_persona_id``, here for the same
    layering reason as ``_resolve_char_context``; keep the two in sync.
    """
    return conv.get("persona_lock_id") or (card.get("persona_lock_id") if card else None) or settings.get("active_persona_id")


async def _build_offturn_prefix(ctx, conv, messages) -> list[ChatMessage]:
    """Rebuild the base prefix the in-turn passes receive -- system prompt,
    character framing, and history -- for the off-turn production path, so a
    manually generated image gets the same context an auto one does. Mirrors the
    pipeline's ``_build_prefix_from_ctx`` through the toolkit surface. Pre-pipeline
    system blocks have no off-turn analogue and are omitted.
    """
    settings = ctx.settings
    card = ctx.character
    system_prompt, char_persona, mes_example = _resolve_char_context(settings, card)
    persona_id = _resolve_persona_id(conv, card, settings)
    persona = None
    if persona_id is not None:
        persona = next((p for p in await get_user_personas() if str(p.get("id")) == str(persona_id)), None)
    macros = Macros.from_settings(settings, conv.get("character_name", ""), persona)
    user_description = persona.get("description", "") if persona else settings.get("user_description", "")
    post_history = "" if settings.get("prevent_prompt_overrides") else conv.get("post_history_instructions", "")
    return build_prefix(
        system_prompt,
        char_persona,
        conv.get("character_scenario", ""),
        mes_example,
        post_history,
        messages,
        macros,
        user_description,
    )


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


async def _generate_core(
    *,
    client,
    prefix,
    char_prompt: str,
    persona_prompt: str,
    moment: str,
    direction_notes: str = "",
    cfg: dict,
    settings,
    kv_tracker=None,
    enabled_tools=None,
    schema_overrides=None,
):
    """Run the scene analyzer, prompt composer, and ComfyUI render for one image.

    Yields the passes' reasoning and phase-status events; on success yields a
    single ``{"type": "artifact", "attachment": <dict>}`` and stops; on any
    LLM-noise or ComfyUI failure yields ``_phase_done`` and stops with no artifact.

    The per-turn auto path and the on-demand production path both drive this, so a
    manually generated image is identical to the one auto-generation would have
    produced. The artifact is handed back as a sentinel rather than persisted here
    so each caller owns its sink: the turn stages it through the framework, the
    on-demand path inserts it. ``kv_tracker`` / ``enabled_tools`` /
    ``schema_overrides`` thread the turn's KV state so the in-turn passes reuse the
    turn's cache; off-turn callers leave them None and pay the cold prompt.
    """
    yield _phase("Analyzing scene...")
    scene: dict = {}
    async for event in analyze_scene(
        client=client,
        prefix=prefix,
        char_prompt=char_prompt,
        moment=moment,
        direction_notes=direction_notes,
        settings=settings,
        pass_id=f"{WORKFLOW_ID}:analyze",
        kv_tracker=kv_tracker,
        enabled_tools=enabled_tools,
        schema_overrides=schema_overrides,
    ):
        if event.get("type") == "result":
            scene = event.get("args") or {}
        else:
            yield event
    if not _scene_ok(scene):
        logger.warning("image_gen: scene analysis produced no usable scene; skipping image")
        yield _phase_done()
        return

    yield _phase("Composing prompt...")
    composed = ""
    async for event in compose_prompt(
        client=client,
        prefix=prefix,
        scene=scene,
        guideline=resolve_guideline(cfg),
        char_prompt=char_prompt,
        persona_prompt=persona_prompt,
        direction_notes=direction_notes,
        settings=settings,
        pass_id=f"{WORKFLOW_ID}:compose",
        kv_tracker=kv_tracker,
        enabled_tools=enabled_tools,
        schema_overrides=schema_overrides,
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

    yield {"type": "artifact", "attachment": _attachment(img, mime, positive, negative, params, cfg["comfy_url"])}
    yield _phase_done()


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
    direction_notes = await _resolve_direction_notes(ctx, ctx.history)
    async for event in _generate_core(
        client=ctx.client,
        prefix=ctx.prefix,
        char_prompt=char_prompt,
        persona_prompt=persona_prompt,
        moment=_moment(ctx.effective_msg, ctx.draft),
        direction_notes=direction_notes,
        cfg=cfg,
        settings=ctx.settings,
        kv_tracker=ctx.kv_tracker,
        enabled_tools=ctx.enabled_tools,
        schema_overrides=ctx.schema_overrides,
    ):
        if event.get("type") == "artifact":
            att = event["attachment"]
            # The framework's attach_artifact validator only stages bytes whose
            # source tag matches the producing workflow.
            att["source"] = f"workflow:{WORKFLOW_ID}"
            yield {"type": "attach_artifact", "attachment": att}
        else:
            yield event


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
    conv = await get_conversation(ctx.conversation_id)
    prefix = await _build_offturn_prefix(ctx, conv, ctx.history) if conv else _cold_prefix(ctx.history)
    direction_notes = await _resolve_direction_notes(ctx, ctx.history)

    att = None
    async for event in _generate_core(
        client=ctx.client,
        prefix=prefix,
        char_prompt=char_prompt,
        persona_prompt=persona_prompt,
        moment=_moment("", text),
        direction_notes=direction_notes,
        cfg=cfg,
        settings=ctx.settings,
    ):
        if event.get("type") == "artifact":
            att = event["attachment"]
    if att is None:
        logger.info("image_gen: regenerate produced no image for attachment %s", ctx.attachment_id)
    return [att] if att else []


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
    if action == "generate":
        return await _generate(ctx, body)
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
    """Render a neutral preview that folds the configured quality/artist/style tags
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


async def _generate(ctx, body):
    """Production render: generate and persist an image for an existing assistant
    message on demand. Validates the target, then returns a streaming response that
    the generic trigger route relays verbatim -- so the passes' live progress
    streams back without a dedicated hook type. Unlike the per-turn path this has no
    per-character enable gate: the toolbar button is itself the explicit request.
    """
    mid = body.get("message_id") if isinstance(body, dict) else None
    if not isinstance(mid, int) or isinstance(mid, bool):
        return {"error": "message_id (int) required"}
    anchor = await get_message_by_id(mid)
    if anchor is None or anchor.get("conversation_id") != ctx.conversation_id:
        return {"error": "message not found in this conversation"}
    if anchor.get("role") != "assistant":
        return {"error": "image generation targets assistant messages"}
    return StreamingResponse(_generate_stream(ctx, anchor), media_type="text/event-stream")


async def _generate_stream(ctx, anchor) -> AsyncIterator[str]:
    """Drive the shared generation core for ``anchor`` and persist the result.

    The image depicts the assistant reply, so the moment pairs that reply with the
    user message it answers -- the anchor's parent. With no turn in flight the
    passes read a freshly rebuilt prefix -- the same system prompt and character
    framing the in-turn passes get -- over the history up to the anchor, never the
    turns after it, and forgo KV reuse.

    The whole body is guarded so the stream always ends with a clean
    ``image_generated`` terminal event. An uncaught exception in a streaming
    response body aborts the chunked transfer without its terminating chunk,
    leaving the client's reader waiting on a stream that never closes; degrading to
    a null result keeps the UI unblocked. The terminal carries the new attachment
    id, or null when generation produced no image.
    """
    new_id = None
    try:
        text = (anchor.get("content") or "").strip()
        if text:
            user_message = ""
            parent_id = anchor.get("parent_id")
            if parent_id:
                parent = await get_message_by_id(parent_id)
                user_message = (parent or {}).get("content") or ""
            before = []
            for message in ctx.history or ():
                if message.get("id") == anchor["id"]:
                    break
                before.append(message)
            conv = await get_conversation(ctx.conversation_id)
            prefix = await _build_offturn_prefix(ctx, conv, before) if conv else _cold_prefix(before)
            cfg = normalize_config(await get_workflow_config(WORKFLOW_ID))
            char_state = await get_workflow_character_state(ctx.character_id, WORKFLOW_ID) if ctx.character_id else None
            char_prompt, persona_prompt = _resolve_prompts(ctx, cfg, char_state)
            direction_notes = await _resolve_direction_notes(ctx, before + [anchor])
            async for event in _generate_core(
                client=ctx.client,
                prefix=prefix,
                char_prompt=char_prompt,
                persona_prompt=persona_prompt,
                moment=_moment(user_message, text),
                direction_notes=direction_notes,
                cfg=cfg,
                settings=ctx.settings,
            ):
                if event.get("type") == "artifact":
                    logger.info("image_gen: render fetched; inserting attachment for message %s", anchor["id"])
                    new_id, _ = await insert_workflow_attachment(anchor["id"], event["attachment"])
                elif event.get("event"):
                    yield _sse(event)
        else:
            yield _sse(_phase_done())
    except Exception:
        logger.exception("image_gen: production generation failed for message %s", anchor.get("id"))
        yield _sse(_phase_done())
    logger.info("image_gen: production generation done for message %s (attachment %s)", anchor.get("id"), new_id)
    yield _sse({"event": "image_generated", "data": {"attachment_id": new_id}})
