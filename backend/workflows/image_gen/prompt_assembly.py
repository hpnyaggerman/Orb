"""Pure value transforms for the image_gen workflow: config normalization, the
two pass instructions, scene rendering, positive/negative assembly, generation
parameters, and the attachment reproduction record.

No conversation, turn, HTTP, or DB state is touched here -- every function maps
its arguments to a value. The hook layer wires these into the pipeline, the
ComfyUI client, and the attachment cache.
"""

from __future__ import annotations

import secrets

# Backend prompting guideline applied when the config field is left empty. A
# booru-tag-oriented default that suits the shipped graph; surfaced to the user
# as the field's placeholder (via the config schema) rather than a stored value,
# so editing it is an explicit override. The tag order is the one the image
# backend expects; the quality block is absent because assemble_positive
# prepends it mechanically.
DEFAULT_GUIDELINE = (
    "Output ONLY a single comma-separated list of danbooru-style tags, in this order: "
    "subject count (1girl, 1boy, 1other, ...), then character names, then series names, "
    "then artist tags, then style tags, then general tags (appearance, outfit, expression, "
    "pose, action, setting, composition). Lowercase, no sentences, no weighting syntax. "
    "Prefer concrete visual tags."
)

# Quality tags and negative prompt applied when their config fields are left
# empty, surfaced to the user as placeholders (via the config schema) rather than
# stored values, so editing either is an explicit override.
DEFAULT_QUALITY_TAGS = "masterpiece, best quality, highly detailed"
DEFAULT_NEGATIVE = "lowres, bad anatomy, bad hands, text, error, watermark, signature"

# Neutral baseline scene the config-preview test feeds the composer pass in
# place of an analyzed moment. Assumes nothing about the subjects' appearance,
# count, or relationship, so the preview exercises the prompt settings rather
# than a specific moment.
TEST_SCENE = "characters sitting in front of a table together"

# Authoritative default config for the workflow's global slot. Also the merge
# base for normalize_config, so a partial or empty persisted slot resolves every
# key. cfg/steps/width/height mirror the shipped graph's baked values so an
# out-of-box config reproduces it.
CONFIG_DEFAULTS: dict = {
    "comfy_url": "http://127.0.0.1:8188",
    "timeout_s": 180.0,
    "artist_tags": "",
    "style_tags": "",
    "quality_tags": "",
    "negative_prompt": "",
    "persona_prompts": {},
    "prompt_guideline": "",
    "cfg": 5.0,
    "steps": 40,
    "width": 1536,
    "height": 1152,
    "seed": -1,
}

_STRING_KEYS = (
    "comfy_url",
    "artist_tags",
    "style_tags",
    "quality_tags",
    "negative_prompt",
    "prompt_guideline",
)

# Upper bound for an injected seed. Kept in lockstep with the reroll_gen hook's
# int(seed, 16) % SEED_MODULUS decode so the seed injected at first render is
# exactly the one rehydrate reconstructs from the stored hex.
SEED_MODULUS = 2**63


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def normalize_config(raw: object) -> dict:
    """Merge a stored/partial config over CONFIG_DEFAULTS with type coercion.

    The config slot is stored as a full replacement that may have round-tripped
    numbers through JSON as strings, so numerics are coerced and persona_prompts
    is forced to a dict; downstream code reads typed values without rechecking.
    """
    out = dict(CONFIG_DEFAULTS)
    if isinstance(raw, dict):
        for key in CONFIG_DEFAULTS:
            val = raw.get(key)
            if val is not None:
                out[key] = val
    out["timeout_s"] = _as_float(out["timeout_s"], CONFIG_DEFAULTS["timeout_s"])
    out["cfg"] = _as_float(out["cfg"], CONFIG_DEFAULTS["cfg"])
    out["steps"] = _as_int(out["steps"], CONFIG_DEFAULTS["steps"])
    out["width"] = _as_int(out["width"], CONFIG_DEFAULTS["width"])
    out["height"] = _as_int(out["height"], CONFIG_DEFAULTS["height"])
    out["seed"] = _as_int(out["seed"], CONFIG_DEFAULTS["seed"])
    if not isinstance(out["persona_prompts"], dict):
        out["persona_prompts"] = {}
    for key in _STRING_KEYS:
        if not isinstance(out[key], str):
            out[key] = CONFIG_DEFAULTS[key] if out[key] is None else str(out[key])
    return out


def compute_seed(cfg: dict) -> int:
    """Resolve the KSampler seed for one render, reduced into [0, SEED_MODULUS).

    A configured seed >= 0 is used fixed; a negative value draws a fresh random
    seed per render. The modulo reduction matches the reroll_gen decode so a
    fixed seed in the upper half of the backend's range reproduces identically
    on rehydrate rather than diverging.
    """
    seed = cfg.get("seed", -1)
    seed = _as_int(seed, -1)
    if seed < 0:
        seed = secrets.randbelow(SEED_MODULUS)
    return seed % SEED_MODULUS


def resolve_gen_params(cfg: dict) -> dict:
    """Collect the graph-bound generation parameters from a normalized config."""
    return {
        "cfg": float(cfg["cfg"]),
        "steps": int(cfg["steps"]),
        "width": int(cfg["width"]),
        "height": int(cfg["height"]),
        "seed": compute_seed(cfg),
    }


def resolve_quality(cfg: dict) -> str:
    """The quality tags prepended to the positive prompt: the user's override, or
    the baked default when the config field is left empty."""
    return (cfg.get("quality_tags") or "").strip() or DEFAULT_QUALITY_TAGS


def _join_tag_sections(*sections: object) -> str:
    """Join tag sections into one comma-separated prompt. Each section is re-split on
    commas and its tags stripped individually, so a stray leading or trailing comma,
    a doubled comma, or a comma-only section never yields an empty tag or a double
    comma in the result. Non-string sections are skipped."""
    tags: list[str] = []
    for section in sections:
        if not isinstance(section, str):
            continue
        for tag in section.split(","):
            tag = tag.strip()
            if tag:
                tags.append(tag)
    return ", ".join(tags)


def assemble_positive(composed: str, cfg: dict) -> str:
    """Prepend the quality tag block to the LLM-composed scene prompt.

    Quality is the only mechanically-placed block. The artist and style tags sit
    mid-order, between the model-owned character/series and general sections, so
    code cannot splice them in without the model marking a boundary -- and the
    model replicates given tags more reliably than it places a boundary marker.
    They travel to the composer via compose_instruction instead."""
    return _join_tag_sections(resolve_quality(cfg), composed)


def resolve_negative(cfg: dict) -> str:
    """The negative prompt: the user's override (sanitized of stray commas), or the
    baked default when the config field is left empty."""
    return _join_tag_sections((cfg.get("negative_prompt") or "").strip() or DEFAULT_NEGATIVE)


def resolve_guideline(cfg: dict) -> str:
    """The prompting guideline fed to Pass 2: the user's override, or the baked
    default when the config field is left empty."""
    return (cfg.get("prompt_guideline") or "").strip() or DEFAULT_GUIDELINE


def build_generation_metadata(positive: str, negative: str, params: dict, comfy_url: str) -> dict:
    """The self-contained reproduction record stored on the attachment.

    Carries the resolved prompt strings and graph parameters so reroll and
    rehydrate -- whose context has no character, history, or config to re-derive
    them from -- reproduce the image without re-running the LLM passes. The seed
    is excluded: the reroll/rehydrate routes supply it as a separate argument.
    """
    return {
        "positive": positive,
        "negative": negative,
        "cfg": params["cfg"],
        "steps": params["steps"],
        "width": params["width"],
        "height": params["height"],
        "comfy_url": comfy_url,
    }


def analyze_instruction(char_prompt: str) -> str:
    """The Pass-1 instruction: extract the scene strictly from what the history
    evidences, defaulting any unestablished attribute to the character's default
    rather than inferring it from genre convention.
    """
    base = (
        "Analyze the moment below and call analyze_scene using ONLY what the history "
        "directly evidences. Make no inferences beyond the text. For every attribute "
        "(outfit, position, pose, action) use the last datapoint -- the most recent "
        "explicit statement in the history; if an attribute was never changed it stays "
        "at the default. Report each present character's outfit as a delta from their "
        "default -- articles added or substituted, and default articles now absent -- "
        "but ONLY where the history states the change. Do NOT infer outfits, poses, or "
        "positions from genre conventions, tropes, or what is typical; when the text "
        "does not establish something, fall back to the default rather than guessing. "
        "Capture spatial positions relative to named objects and to each other, current "
        "poses, and the action in this exact moment."
    )
    if char_prompt and char_prompt.strip():
        base += "\n\nDefault appearance and outfit for the main character:\n" + char_prompt.strip()
    return base


def compose_instruction(
    guideline: str,
    char_prompt: str,
    persona_prompt: str,
    artist_tags: str = "",
    style_tags: str = "",
) -> str:
    """The Pass-2 framing: guideline, character and persona base prompts, and the
    configured artist/style tags the model must replicate at their guideline
    positions. Replication is the model's duty because those slots fall between
    its character/series and general sections, where code cannot splice.

    The analyzed scene is appended after this block by the caller so it lands last
    in the model's context.
    """
    parts = ["Compose ONE positive image-generation prompt depicting exactly the scene described last."]
    if guideline and guideline.strip():
        parts.append("Follow this backend prompting guideline:\n" + guideline.strip())
    if char_prompt and char_prompt.strip():
        parts.append("Character base description:\n" + char_prompt.strip())
    if persona_prompt and persona_prompt.strip():
        parts.append("User-persona base description:\n" + persona_prompt.strip())
    if artist_tags and artist_tags.strip():
        parts.append("Artist tags -- replicate EXACTLY as given, at the guideline's artist position:\n" + artist_tags.strip())
    if style_tags and style_tags.strip():
        parts.append("Style tags -- replicate EXACTLY as given, at the guideline's style position:\n" + style_tags.strip())
    parts.append(
        "Quality tags are prepended automatically; do not emit them. "
        "Apply each outfit delta onto the base description, then call compose_image_prompt."
    )
    return "\n\n".join(parts)


def render_scene_block(scene: object) -> str:
    """Render the structured scene dict as compact plain text for Pass 2.

    A str passes through unchanged -- the config-preview test supplies its
    baseline scene as free text in place of an analyzed dict. Tolerant of
    missing or malformed fields: any absent section is dropped so a partial
    scene from the model still yields usable text.
    """
    if isinstance(scene, str):
        return scene
    if not isinstance(scene, dict):
        return ""
    lines: list[str] = []
    present = [str(c) for c in (scene.get("characters_present") or []) if c]
    if present:
        lines.append("Characters present: " + ", ".join(present))
    for outfit in scene.get("outfits") or []:
        if not isinstance(outfit, dict):
            continue
        name = str(outfit.get("character", "")).strip() or "character"
        added = [str(a) for a in (outfit.get("added_articles") or []) if a]
        removed = [str(a) for a in (outfit.get("removed_default_articles") or []) if a]
        seg = f"{name} outfit:"
        if added:
            seg += " wearing " + ", ".join(added) + ";"
        if removed:
            seg += " without " + ", ".join(removed) + ";"
        if not added and not removed:
            seg += " default outfit;"
        lines.append(seg)
    anchors = [str(a) for a in (scene.get("anchors") or []) if a]
    if anchors:
        lines.append("Scene anchors: " + ", ".join(anchors))
    for pos in scene.get("positions") or []:
        if not isinstance(pos, dict):
            continue
        name = str(pos.get("character", "")).strip() or "character"
        bits = []
        if pos.get("relative_to_anchor"):
            bits.append(str(pos["relative_to_anchor"]))
        if pos.get("relative_to_others"):
            bits.append(str(pos["relative_to_others"]))
        if bits:
            lines.append(f"{name} position: " + "; ".join(bits))
    for pose in scene.get("poses") or []:
        if isinstance(pose, dict) and pose.get("pose"):
            name = str(pose.get("character", "")).strip() or "character"
            lines.append(f"{name} pose: {pose['pose']}")
    for action in scene.get("actions") or []:
        if isinstance(action, dict) and action.get("action"):
            name = str(action.get("character", "")).strip() or "character"
            lines.append(f"{name} action: {action['action']}")
    return "\n".join(lines)
