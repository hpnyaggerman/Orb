"""Instruction prompts owned by the Director passes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ....prompting.tool_catalog import get_tool, require_tool
from ....prompting.tool_schemas import wire_field
from .._prompting import REASONING_GUIDANCE, tool_call_instruction

DIRECTOR_PREAMBLE = (
    "[OOC: Pause to direct the scene. Use tool calls to accomplish your task "
    "accurately and creatively. Your output will directly influence the scenario. "
    "Think outside the box, be intentional."
)


def _moods_options_block(active_moods: Sequence[str], mood_fragments: Sequence[Mapping[str, Any]]) -> str:
    moods = ", ".join(wire_field(mood) for mood in active_moods) or "none"
    fragments = "\n".join(
        f"* [{wire_field(fragment['id'])}] - use in case: {fragment['description']}" for fragment in mood_fragments
    )
    return f"Previously active moods: {moods}\n\nAvailable writing moods:\n{fragments}"


def build_director_tool_prompt(
    tool_name: str,
    user_message: str,
    active_moods: list[str],
    mood_fragments: Sequence[Mapping[str, Any]],
    reasoning_on: bool = False,
    interactive_fragments: Sequence[Mapping[str, Any]] | None = None,
    progressive_state: dict | None = None,
    tool_schema: dict | None = None,
    cast_instruction: str = "",
    named_fields: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Build the combined Director request for one tool.

    *named_fields* are fields whose description names the speaker being directed,
    which the shared schema words neutrally; they are restated with the name.
    """
    tool = get_tool(tool_name)
    if not tool:
        return ""
    schema = tool_schema if tool_schema is not None else tool["schema"]
    preamble = DIRECTOR_PREAMBLE + (REASONING_GUIDANCE if reasoning_on else "")
    parts = [preamble, tool_call_instruction(tool_name, schema)]
    if tool_name == "direct_scene":
        if cast_instruction:
            parts.append(cast_instruction)
        if named_fields:
            parts.append(
                "Field descriptions for this reply:\n"
                + "\n".join(f"* [{wire_field(fragment['id'])}] {fragment['description']}" for fragment in named_fields)
            )
        progressive_lines = [
            f"* [{wire_field(fragment['id'])}] ({fragment['description']}): {(progressive_state or {}).get(fragment['id'])}"
            for fragment in (interactive_fragments or [])
            if fragment.get("field_type") == "progressive" and (progressive_state or {}).get(fragment["id"])
        ]
        if progressive_lines:
            parts.append("Previous progressive fields - dynamically update these:\n" + "\n".join(progressive_lines))
        parts.append(_moods_options_block(active_moods, mood_fragments))
        parts.append(f'User\'s next message (for context, take this into account when directing):\n"""{user_message}"""')
    return "\n\n".join(parts) + "]"


def _render_decided(value: Any) -> str:
    return ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)


def build_director_scene_step_prompt(
    user_message: str,
    active_moods: list[str],
    mood_fragments: Sequence[Mapping[str, Any]],
    *,
    tool_schema: dict | None = None,
    reasoning_on: bool = False,
    target_fragment: Mapping[str, Any] | None = None,
    decided_fields: Sequence[tuple[str, Any]] = (),
    progressive_prior: Any = None,
    cast_instruction: str = "",
) -> str:
    """Build one ``direct_scene`` request targeting a single output."""
    schema = tool_schema if tool_schema is not None else require_tool("direct_scene")["schema"]
    description = schema["function"]["description"]
    parts = [DIRECTOR_PREAMBLE + (REASONING_GUIDANCE if reasoning_on else "")]

    if target_fragment is None:
        parts.append(f"Call ONLY direct_scene - {description}\nFill ONLY: moods.")
        scene = [f"- {label}: {_render_decided(value)}" for label, value in decided_fields if value]
        if scene:
            parts.append("Scene direction decided this turn (pick moods that fit it):\n" + "\n".join(scene))
        parts.append(_moods_options_block(active_moods, mood_fragments))
    else:
        fragment_id = wire_field(target_fragment["id"])
        hint = {
            "array": "list of strings",
            "progressive": "single value, evolves across turns",
        }.get(target_fragment["field_type"], "single value")
        parts.append(
            f"Call ONLY direct_scene - {description}\nFill ONLY the '{fragment_id}' parameter. "
            "Leave moods and all other fields empty."
        )
        parts.append(f"Field '{fragment_id}' ({hint}): {target_fragment['description']}")
        if cast_instruction:
            parts.append(cast_instruction)
        prior = [f"- {label}: {_render_decided(value)}" for label, value in decided_fields if value]
        if prior:
            parts.append("Decided so far this turn (build on these, do not contradict):\n" + "\n".join(prior))
        if target_fragment["field_type"] == "progressive" and progressive_prior:
            parts.append(f"Previous value (update it): {progressive_prior}")

    parts.append(f'User\'s next message (context):\n"""{user_message}"""')
    return "\n\n".join(parts) + "]"


def build_lorebook_select_prompt(catalog: str, user_message: str) -> str:
    """Build the standalone Agentic Lorebook selection request.

    Opens with its own framing instead of ``DIRECTOR_PREAMBLE`` and never takes
    ``REASONING_GUIDANCE``: their stance (creative, intentional, don't
    overthink) is written for directing and nudges a lookup toward picking few
    entries, while this step must catch every entry that applies.
    """
    parts = [
        "[OOC: Pause to gather the lore the next reply needs.",
        (
            "Call ONLY select_lorebook. Check the catalog below entry by entry and select every entry that "
            "bears on the scene: the conversation so far plus the user's next message (quoted after the "
            "catalog). An entry bears on the scene when it covers:\n"
            "- a character who is present, mentioned, or closely tied to someone present\n"
            "- the current location, or the wider place it belongs to\n"
            "- a faction, group, species, title, or role of anyone involved\n"
            "- an object, ability, custom, rule, or phenomenon in use or referenced\n"
            "- a past event or relationship being alluded to\n"
            "- anything the user's next message introduces, asks about, or heads toward\n"
            "Lore from earlier in the conversation counts while it is still in play. A left-out entry may be "
            "missing when the next reply is written, while an extra one costs little, so include borderline "
            "entries. Leave out only entries with no connection to the scene."
        ),
        catalog,
        f'User\'s next message:\n"""{user_message}"""',
    ]
    return "\n\n".join(parts) + "]"
