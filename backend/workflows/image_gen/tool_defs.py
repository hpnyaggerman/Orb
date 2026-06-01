"""Forced-call tool schemas for the image_gen passes.

Two standalone tools, registered into the global ``TOOLS`` registry through the
workflow's ``Workflow.tools`` so ``forced_tool_call`` can resolve them by name.
``analyze_scene`` is structured so the required scene components (per-character
outfit delta, spatial anchors, poses, actions) are enforced by the schema rather
than parsed out of prose; ``compose_image_prompt`` returns the single positive
prompt string the ComfyUI graph consumes.
"""

from __future__ import annotations

ANALYZE_SCENE_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_scene",
        "description": (
            "Describe the depicted moment for image generation: who is present, each "
            "character's outfit as a delta from their default, where they are relative to "
            "objects and each other, their poses, and the action at this moment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "characters_present": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of the characters visible in this moment.",
                },
                "outfits": {
                    "type": "array",
                    "description": "One entry per present character, as a delta from their default outfit.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character": {"type": "string"},
                            "added_articles": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Articles worn in addition to, or in place of, the defaults.",
                            },
                            "removed_default_articles": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Default articles that are absent in this moment.",
                            },
                        },
                        "required": ["character"],
                    },
                },
                "anchors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Objects in the scene that characters are positioned against.",
                },
                "positions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character": {"type": "string"},
                            "relative_to_anchor": {"type": "string"},
                            "relative_to_others": {"type": "string"},
                        },
                        "required": ["character"],
                    },
                },
                "poses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character": {"type": "string"},
                            "pose": {"type": "string"},
                        },
                        "required": ["character", "pose"],
                    },
                },
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character": {"type": "string"},
                            "action": {"type": "string"},
                        },
                        "required": ["character", "action"],
                    },
                },
            },
            "required": ["characters_present", "outfits", "anchors", "positions", "poses", "actions"],
        },
    },
}

ANALYZE_SCENE_CHOICE = {"type": "function", "function": {"name": "analyze_scene"}}

COMPOSE_PROMPT_TOOL = {
    "type": "function",
    "function": {
        "name": "compose_image_prompt",
        "description": (
            "Compose one positive image-generation prompt that depicts exactly the analyzed "
            "scene, following the provided backend prompting guideline."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "positive_prompt": {
                    "type": "string",
                    "description": "The positive prompt for the image backend.",
                },
            },
            "required": ["positive_prompt"],
        },
    },
}

COMPOSE_PROMPT_CHOICE = {"type": "function", "function": {"name": "compose_image_prompt"}}
