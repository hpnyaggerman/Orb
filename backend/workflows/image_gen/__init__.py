"""Image-generation workflow.

Per turn it analyzes the just-produced reply, composes an image-generation
prompt, renders it through a ComfyUI backend, and attaches the image to the
assistant message. The ComfyUI client and the pure prompt/graph logic live in
submodules that carry no workflow-framework reference, so they stay
independently importable and testable; workflow binding (registration metadata
and hooks) is wired in ``backend/workflows/__init__.py``.

The standalone tools are declared here so ``register_workflow`` inserts them
into the global tool registry, which is where ``forced_tool_call`` resolves them
for the passes. ``standalone=True`` keeps them out of the director/writer/
editor tool union.
"""

from __future__ import annotations

from backend.workflows.contracts import ToolSpec
from backend.workflows.registry import Workflow

from .prompt_assembly import (
    CONFIG_DEFAULTS,
    DEFAULT_GUIDELINE,
    DEFAULT_NEGATIVE,
    DEFAULT_QUALITY_TAGS,
)
from .tool_defs import (
    ANALYZE_SCENE_CHOICE,
    ANALYZE_SCENE_TOOL,
    COMPOSE_PROMPT_CHOICE,
    COMPOSE_PROMPT_TOOL,
    INFER_TRAITS_CHOICE,
    INFER_TRAITS_TOOL,
)

# Informational schema surfaced in the manifest. The config form is hand-built
# in the frontend module, so this documents the slot rather than generating it.
_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "comfy_url": {"type": "string", "title": "ComfyUI base URL"},
        "timeout_s": {"type": "number", "minimum": 1, "title": "Render timeout (seconds)"},
        "artist_tags": {"type": "string", "title": "Artist tags (prepended)"},
        "style_tags": {"type": "string", "title": "Style tags (prepended)"},
        "quality_tags": {"type": "string", "title": "Quality tags (prepended)", "default": DEFAULT_QUALITY_TAGS},
        "negative_prompt": {"type": "string", "title": "Negative prompt", "default": DEFAULT_NEGATIVE},
        "persona_prompts": {"type": "object", "title": "Per-persona prompts"},
        "prompt_guideline": {"type": "string", "title": "Backend prompting guideline", "default": DEFAULT_GUIDELINE},
        "infer_char_traits": {"type": "boolean", "title": "Infer character description from chat context"},
        "infer_persona_traits": {"type": "boolean", "title": "Infer persona description from chat context"},
        "cfg": {"type": "number", "title": "CFG scale"},
        "steps": {"type": "integer", "minimum": 1, "title": "Sampling steps"},
        "width": {"type": "integer", "minimum": 1, "title": "Image width"},
        "height": {"type": "integer", "minimum": 1, "title": "Image height"},
        "seed": {"type": "integer", "title": "Fixed seed (negative for random)"},
    },
}

image_gen_workflow = Workflow(
    id="image_gen",
    display_name="Image Generation",
    produces_artifacts=True,
    config_schema=_CONFIG_SCHEMA,
    config_defaults=dict(CONFIG_DEFAULTS),
    tools=[
        ToolSpec(name="infer_subject_traits", schema=INFER_TRAITS_TOOL, choice=INFER_TRAITS_CHOICE, standalone=True),
        ToolSpec(name="analyze_scene", schema=ANALYZE_SCENE_TOOL, choice=ANALYZE_SCENE_CHOICE, standalone=True),
        ToolSpec(name="compose_image_prompt", schema=COMPOSE_PROMPT_TOOL, choice=COMPOSE_PROMPT_CHOICE, standalone=True),
    ],
)
