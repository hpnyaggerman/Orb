"""Prompt construction for the analyzer, judge, and enforcer.

Pure string assembly: preambles, the rendered spec/schema/violation blocks, and
the per-pass task instructions. The message-stack wiring (which block is a
system message vs a trailing user message, per prompt mode) lives in ``loop.py``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# Recent assistant messages the analyzer reads to infer the convention. The
# format is conventionally stable across a conversation, so a small window is
# enough and keeps the one-shot analyzer prompt cheap.
ANALYZER_SAMPLE_WINDOW = 8

ANALYZER_PREAMBLE = (
    "You are a prose-format analyzer for a roleplay chat. From a conversation's assistant prose, "
    "you infer how each listed prose element is marked (its delimiters/convention) and record a "
    "short description of it. Judge only from the text shown, not from the element's guidance."
)

JUDGE_PREAMBLE = (
    "You are a prose-format judge for a roleplay chat. Given the recorded prose format and a draft "
    "reply, you locate spans of the draft that break the recorded format. You only locate and "
    "categorize -- you never rewrite, suggest fixes, or explain."
)

ENFORCER_PREAMBLE = (
    "You are a prose-format enforcer for a roleplay chat. You apply the smallest edits that bring "
    "flagged spans into the recorded format, changing only markup -- never the wording, meaning, or "
    "content of the prose."
)

_ANALYZE_TASK = (
    "For each element below, describe how it is denoted in the prose above. Skip any element you see "
    "no evidence for. Call {tool} with one record per element you can characterize.\n\nElements:\n{schema}"
)

_JUDGE_TASK = (
    "Find every span of the draft that breaks the recorded prose format. For each, give the exact "
    "offending text (copied verbatim from the draft) and the single element name it violates. Do not "
    "report compliant text. Call {tool}."
)

_ENFORCE_TASK = (
    "Each flagged span below violates the recorded format. For each, emit a patch whose 'search' is "
    "the span copied verbatim from the draft and whose 'replace' is that span rewritten to the "
    "recorded format, with every word preserved. Call {tool}.\n\nFlagged spans:\n{violations}"
)


def render_spec_block(spec: Mapping[str, str]) -> str:
    """The recorded format the judge/enforcer hold the draft to, one element per line."""
    return "\n".join(f"- {k}: {v}" for k, v in spec.items())


def render_schema_block(schema: Mapping[str, str]) -> str:
    """The analyzer's element list: name plus the guidance description for each."""
    return "\n".join(f"- {k}: {v}" for k, v in schema.items())


def render_violations(violations: Sequence[Mapping[str, str]]) -> str:
    """The judge's findings, formatted for the enforcer: one ``[category] excerpt`` per line."""
    return "\n".join(f"- [{v['category']}] {v['excerpt']}" for v in violations)


def recent_assistant_prose(history: Sequence[Any]) -> str:
    """Up to ANALYZER_SAMPLE_WINDOW recent assistant messages, oldest-first, joined.

    Assistant history is always plain text; a non-string body (the multimodal
    list form rides only user messages) carries no prose to sample.
    """
    window: list[str] = []
    for msg in reversed(history):
        if not isinstance(msg, Mapping) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            window.append(content)
            if len(window) >= ANALYZER_SAMPLE_WINDOW:
                break
    window.reverse()
    return "\n\n".join(window)


def analyze_instruction(schema: Mapping[str, str], history: Sequence[Any], tool: str) -> str:
    """The analyzer's trailing user message: prose samples plus the element list."""
    samples = recent_assistant_prose(history) or "(no prior assistant prose)"
    task = _ANALYZE_TASK.format(tool=tool, schema=render_schema_block(schema))
    return f"Recent assistant prose:\n{samples}\n\n{task}"


def judge_instruction(tool: str) -> str:
    return _JUDGE_TASK.format(tool=tool)


def enforce_instruction(violations: Sequence[Mapping[str, str]], tool: str) -> str:
    return _ENFORCE_TASK.format(tool=tool, violations=render_violations(violations))
