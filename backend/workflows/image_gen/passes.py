"""The image_gen LLM passes, each a thin async generator over
``forced_tool_call``.

Both own their message-tail assembly so the hook layer stays focused on flow.
The composer deliberately places the analyzed scene as the final message, after
the guideline/character/persona framing, so the scene conclusions sit at the end
of the model's context window where they are attended to most strongly. Each
generator forwards reasoning events and ends with the terminal
``{"type": "result", "args": <dict>}`` event from ``forced_tool_call``.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Sequence

from backend.workflows.toolkit import forced_tool_call

from .prompt_assembly import (
    analyze_instruction,
    compose_instruction,
    infer_instruction,
    render_scene_block,
)

logger = logging.getLogger(__name__)


async def infer_traits(
    *,
    client: Any,
    prefix: Sequence[dict],
    infer_char: bool,
    infer_persona: bool,
    char_prompt: str,
    persona_prompt: str,
    moment: str,
    settings: Any,
    direction_notes: str = "",
    pass_id: str | None = None,
    kv_tracker: Any = None,
    enabled_tools: Any = None,
    schema_overrides: Any = None,
) -> AsyncIterator[dict]:
    instruction = infer_instruction(infer_char, infer_persona, char_prompt, persona_prompt, direction_notes)
    tail = [{"role": "user", "content": instruction + "\n\n" + moment}]
    async for event in forced_tool_call(
        client=client,
        prefix=prefix,
        tail_messages=tail,
        tool_name="infer_subject_traits",
        settings=settings,
        pass_id=pass_id,
        enabled_tools=enabled_tools,
        schema_overrides=schema_overrides,
        kv_tracker=kv_tracker,
        temperature=0.4,
    ):
        if event.get("type") == "result":
            logger.info("image_gen: infer_subject_traits tool result: %s", event.get("args"))
        yield event


async def analyze_scene(
    *,
    client: Any,
    prefix: Sequence[dict],
    char_prompt: str,
    moment: str,
    settings: Any,
    direction_notes: str = "",
    pass_id: str | None = None,
    kv_tracker: Any = None,
    enabled_tools: Any = None,
    schema_overrides: Any = None,
) -> AsyncIterator[dict]:
    tail = [{"role": "user", "content": analyze_instruction(char_prompt, direction_notes) + "\n\n" + moment}]
    async for event in forced_tool_call(
        client=client,
        prefix=prefix,
        tail_messages=tail,
        tool_name="analyze_scene",
        settings=settings,
        pass_id=pass_id,
        enabled_tools=enabled_tools,
        schema_overrides=schema_overrides,
        kv_tracker=kv_tracker,
        temperature=0.4,
    ):
        if event.get("type") == "result":
            logger.info("image_gen: analyze_scene tool result: %s", event.get("args"))
        yield event


async def compose_prompt(
    *,
    client: Any,
    prefix: Sequence[dict],
    scene: dict,
    guideline: str,
    char_prompt: str,
    persona_prompt: str,
    settings: Any,
    direction_notes: str = "",
    pass_id: str | None = None,
    kv_tracker: Any = None,
    enabled_tools: Any = None,
    schema_overrides: Any = None,
) -> AsyncIterator[dict]:
    tail = [
        {"role": "user", "content": compose_instruction(guideline, char_prompt, persona_prompt, direction_notes)},
        {"role": "user", "content": render_scene_block(scene)},
    ]
    async for event in forced_tool_call(
        client=client,
        prefix=prefix,
        tail_messages=tail,
        tool_name="compose_image_prompt",
        settings=settings,
        pass_id=pass_id,
        enabled_tools=enabled_tools,
        schema_overrides=schema_overrides,
        kv_tracker=kv_tracker,
        temperature=0.5,
    ):
        if event.get("type") == "result":
            logger.info("image_gen: compose_image_prompt tool result: %s", event.get("args"))
        yield event
