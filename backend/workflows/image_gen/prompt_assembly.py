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
# so editing it is an explicit override.
DEFAULT_GUIDELINE = (
    "Output ONLY a single comma-separated list of danbooru-style tags. Order subject-first: "
    "character count and identity, then appearance, outfit, expression, pose, then setting and "
    "composition. Lowercase, no sentences, no weighting syntax. Prefer concrete visual tags."
)

# Quality tags and negative prompt applied when their config fields are left
# empty, surfaced to the user as placeholders (via the config schema) rather than
# stored values, so editing either is an explicit override.
DEFAULT_QUALITY_TAGS = "masterpiece, best quality, highly detailed"
DEFAULT_NEGATIVE = "lowres, bad anatomy, bad hands, text, error, watermark, signature"

# Neutral baseline scene for the config-preview test. Places the configured
# subjects in a simple composition without assuming anything about their
# appearance, count, or relationship, so the preview exercises the prompt
# settings rather than a specific moment.
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


def _tag_prefix(cfg: dict) -> list[str]:
    """The quality, style, and artist tags, in the single order every positive
    prompt -- per-turn render and config test alike -- prepends them. Quality falls
    back to its baked default; style and artist are optional."""
    return [resolve_quality(cfg), cfg.get("style_tags", ""), cfg.get("artist_tags", "")]


def assemble_positive(composed: str, cfg: dict) -> str:
    """Prepend the quality/style/artist tag prefix to the LLM-composed scene prompt."""
    parts = [*_tag_prefix(cfg), composed or ""]
    cleaned = [p.strip().strip(",").strip() for p in parts if isinstance(p, str) and p.strip()]
    return ", ".join(cleaned)


def build_test_positive(cfg: dict, char_prompt: str, persona_prompt: str) -> str:
    """The positive prompt for the config-preview test: the same quality/style/artist
    tag prefix as a real render, then the character and persona prompts, then the
    neutral baseline scene. Empty pieces are dropped, so nothing about the character
    or persona is assumed when either is unset."""
    parts = [*_tag_prefix(cfg), char_prompt or "", persona_prompt or "", TEST_SCENE]
    cleaned = [p.strip().strip(",").strip() for p in parts if isinstance(p, str) and p.strip()]
    return ", ".join(cleaned)


def resolve_negative(cfg: dict) -> str:
    """The negative prompt: the user's override, or the baked default when the
    config field is left empty."""
    return (cfg.get("negative_prompt") or "").strip() or DEFAULT_NEGATIVE


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
    """The Pass-1 instruction: extract the scene as a structured outfit delta.

    The character's default outfit is supplied so the model reports what is added
    or absent relative to it rather than re-describing the whole appearance.
    """
    base = (
        "Analyze the moment below and call analyze_scene with exactly what is visible. "
        "Report each present character's outfit as a delta from their default: articles added "
        "or substituted, and default articles now absent. Capture spatial positions relative to "
        "named objects and to each other, current poses, and the action in this exact moment."
    )
    if char_prompt and char_prompt.strip():
        base += "\n\nDefault appearance and outfit for the main character:\n" + char_prompt.strip()
    return base


def compose_instruction(guideline: str, char_prompt: str, persona_prompt: str) -> str:
    """The Pass-2 framing: guideline plus the character and persona base prompts.

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
    parts.append("Apply each outfit delta onto the base description, then call compose_image_prompt.")
    return "\n\n".join(parts)


def render_scene_block(scene: object) -> str:
    """Render the structured scene dict as compact plain text for Pass 2.

    Tolerant of missing or malformed fields: any absent section is dropped so a
    partial scene from the model still yields usable text.
    """
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
