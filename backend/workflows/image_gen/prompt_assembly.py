"""Pure value transforms for the image_gen workflow: config normalization, the
pass instructions, scene rendering, positive/negative assembly, generation
parameters, and the attachment reproduction record.

No conversation, turn, HTTP, or DB state is touched here -- every function maps
its arguments to a value. The hook layer wires these into the pipeline, the
ComfyUI client, and the attachment cache.
"""

from __future__ import annotations

import secrets

# Backend prompting guideline applied when the config field is left empty. A
# step-by-step procedure (count -> classify -> identity -> outfit -> per-character
# sentences -> interaction/setting -> camera -> emphasis -> final check) mixing
# booru tags and natural language; surfaced to the user as the field's placeholder
# (via the config schema) rather than a stored value, so editing it is an explicit
# override. Raw string: the examples carry booru-escaped parens (\( \)).
DEFAULT_GUIDELINE = r"""You compose one prompt for a booru-tag image model from the scene description and the character base blocks. Code prepends quality, artist, style, safety, meta, and year tags; begin at the count tag and write none of them: no masterpiece, best quality, score tags, @artists, safe, sensitive, nsfw, explicit, highres, absurdres, newest, or year tags.

Step 1, count. Read the Characters present line. Decide girl, boy, or other for each listed name from the count tag in their base block or from scene pronouns; skip anyone unlisted, including the persona. First write one combined tally, never recopying count tags from the blocks: 1girl, 2girls, 1boy, 1other, or 1boy, 1girl; add solo for one.

Step 2, classify. In each base block look for a booru character tag: a lowercase name, sometimes with escaped parentheses, usually followed by a series tag. Found: KNOWN. Only appearance and outfit tags: ORIGINAL. No block: KNOWN only if you recognize a famous franchise character the image model was trained on, else ORIGINAL.

Step 3, identity. Copy each KNOWN character's tag exactly, then its series tag, keeping escapes: elaina \(majo no tabitabi\). ORIGINAL characters get nothing here.

Step 4, outfit. Take each character's base outfit list; from their scene outfit line, add articles after wearing, delete articles after without; default outfit keeps the base list. Mention only final-list items; never write without X or no X, naming an item makes it appear.

Step 5, one sentence per character. Gather appearance (base block), final outfit (step 4), and the position, pose, action lines. Referent: KNOWN, the capitalized name, Megumin; ORIGINAL, a descriptor from their appearance tags, a tall woman with short silver hair and red eyes, never the name, which the model does not know and may collide. Turn each position line into left, right, center, or behind relative to the anchor or the other character. Then write it: referent, appearance, outfit, position, pose, action, expression. Restate every ORIGINAL character's hair, eyes, and outfit; keep each attribute inside its owner's sentence, never as loose tags.

Example, original solo: 1girl, solo, a young woman with long silver hair, violet eyes, and a black coat stands on a rainy street at night, arms crossed, calm expression. neon lights, cowboy shot, from side

Example, known plus original: 2girls, sorakado ao \(summer pockets\), summer pockets, Sorakado Ao (blue hair, purple eyes) stands on the left in a miko kimono, laughing. A pink-twintailed girl in a school uniform pouts at her from the right. indoors, full body

Step 6, interaction, setting, background. When action lines connect characters, pick the single most visual instant and write one sentence naming who does what to whom; then, after, starts to signal you kept two instants, cut back to one. From the Scene anchors line write one sentence placing the characters at the location with the one or two anchors they use, inferring lighting from time and place. Figures missing from Characters present go only in a background phrase: in the background, a nervous waitress.

Step 7, camera. Decide distance by asking what must stay visible, then write the tightest tag that shows it: faces or emotion, close-up or upper body; outfit, pose, or action, cowboy shot or full body; three or more characters or the place itself, wide shot. Straight-on needs no angle tag; otherwise at most one: from above (lying, vulnerable), from below (dominance), from side (profile), from behind (hides faces), dutch angle (action or unease only). pov only for scenes seen through the persona's eyes, persona shown as hands at most; add looking at viewer only when someone faces the viewer. Last, one tag per true answer: indoors or outdoors? light source (sunset, backlighting)? fast motion (motion blur)? Skip tags that add nothing.

Step 8, emphasis. Is one concept load-bearing for the scene and likely to be missed? Weight only that at 1.5 to 2: (cross counter:1.5). Otherwise weight nothing.

Step 9, final check: only the prompt string, starting at the count tags, lowercase tags with spaces, capitals only in names inside sentences, at least two sentences, 40 to 140 words, one moment."""

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
    "infer_char_traits": False,
    "infer_persona_traits": False,
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
    for key in ("infer_char_traits", "infer_persona_traits"):
        out[key] = bool(out[key])
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
    """The quality, artist, and style tags, in the single order every positive
    prompt -- per-turn render and config test alike -- prepends them. Quality
    falls back to its baked default; artist and style are optional.

    All three are prepended mechanically rather than placed mid-prompt by the
    composer. The booru convention of a mid-order artist slot is learned from
    training data but is ill-motivated for this graph, and front-loading the
    three blocks measured better here; keep them mechanical, not model-placed.
    """
    return [resolve_quality(cfg), cfg.get("artist_tags", ""), cfg.get("style_tags", "")]


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
    """Prepend the quality/artist/style tag prefix to the LLM-composed scene prompt."""
    return _join_tag_sections(*_tag_prefix(cfg), composed)


def build_test_positive(cfg: dict, char_prompt: str, persona_prompt: str) -> str:
    """The positive prompt for the config-preview test: the same quality/artist/style
    tag prefix as a real render, then the character and persona prompts, then the
    neutral baseline scene. Empty pieces are dropped, so nothing about the character
    or persona is assumed when either is unset."""
    return _join_tag_sections(*_tag_prefix(cfg), char_prompt, persona_prompt, TEST_SCENE)


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


def _infer_subject_line(field: str, subject: str, existing: str) -> str:
    """One requested-subject line for ``infer_instruction``, folding in the
    user-authored description as optional material when one exists."""
    line = f"Requested: {field} -- {subject}."
    if existing and existing.strip():
        line += (
            " An existing user-authored description follows; optionally include, refine, "
            "or extend it where the conversation supports doing so:\n" + existing.strip()
        )
    return line


def infer_instruction(
    infer_char: bool,
    infer_persona: bool,
    char_prompt: str = "",
    persona_prompt: str = "",
    direction_notes: str = "",
) -> str:
    """The inference-pass instruction: derive base visual descriptions for the
    requested subjects from the conversation, in the same shape the user-authored
    prompt fields carry, so the analyzer and composer consume them unchanged.

    Existing user-authored values ride along per side as material the model may
    optionally include; a non-requested side is pinned to an empty string.
    *direction_notes* is the pre-rendered Direction Notes block (empty when
    injection is off or the branch has none).
    """
    parts = [
        "Infer base visual descriptions from the conversation, then call "
        "infer_subject_traits. A base description is the subject's lasting baseline -- "
        "identity, appearance, and default outfit -- not the current moment's pose, "
        "action, or temporary state.",
        "For each requested subject: if it is a recognizable known character, give the "
        'character tag (and series tag) exactly, e.g. "rem, re:zero kara hajimeru '
        'isekai seikatsu". Otherwise emit comma-separated booru-style tags for every '
        "stable visual trait the conversation establishes or clearly implies: hair "
        "color, length, and style, eye color, skin, body type, distinguishing features, "
        "and default outfit articles. Do not invent traits the conversation contradicts; "
        "when the conversation establishes nothing about a requested subject, return an "
        "empty string for it.",
    ]
    if infer_char:
        parts.append(_infer_subject_line("character_description", "the main character the assistant plays", char_prompt))
    else:
        parts.append("Not requested: return an empty string for character_description.")
    if infer_persona:
        parts.append(_infer_subject_line("persona_description", "the user's character", persona_prompt))
    else:
        parts.append("Not requested: return an empty string for persona_description.")
    if direction_notes and direction_notes.strip():
        parts.append(
            "Lasting developments already established on this branch -- fold any that "
            "change a subject's identity, appearance, or default outfit into the "
            "descriptions:\n" + direction_notes.strip()
        )
    return "\n\n".join(parts)


def analyze_instruction(char_prompt: str, direction_notes: str = "") -> str:
    """The Pass-1 instruction: extract the scene strictly from what the history
    evidences, defaulting any unestablished attribute to the character's default
    rather than inferring it from genre convention.

    *direction_notes* is the pre-rendered Direction Notes block (empty when injection
    is off or the branch has none); appended after the character default so the scene
    extraction carries forward lasting developments the immediate moment may not restate.
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
    if direction_notes and direction_notes.strip():
        base += (
            "\n\nLasting developments already established on this branch -- treat as true and "
            "fold any that change a character's appearance, outfit, or the setting into the "
            "scene you extract:\n" + direction_notes.strip()
        )
    return base


def compose_instruction(guideline: str, char_prompt: str, persona_prompt: str, direction_notes: str = "") -> str:
    """The Pass-2 framing: guideline plus the character and persona base prompts.

    The analyzed scene is appended after this block by the caller so it lands last
    in the model's context. *direction_notes* is the pre-rendered Direction Notes block
    (empty when injection is off or the branch has none); it rides this framing, before
    the scene, so lasting developments reach the composed prompt without displacing the
    scene from the final position.
    """
    parts = ["Compose ONE positive image-generation prompt depicting exactly the scene described last."]
    if guideline and guideline.strip():
        parts.append("Follow this backend prompting guideline:\n" + guideline.strip())
    if char_prompt and char_prompt.strip():
        parts.append("Character base description:\n" + char_prompt.strip())
    if persona_prompt and persona_prompt.strip():
        parts.append("User-persona base description:\n" + persona_prompt.strip())
    if direction_notes and direction_notes.strip():
        parts.append(
            "Lasting developments already established -- apply any that affect appearance, "
            "outfit, or setting to the prompt:\n" + direction_notes.strip()
        )
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
