"""Format-consistency workflow.

A deterministic, no-LLM post-pipeline normalizer: it reads the dialogue /
narration markup convention of the recent assistant messages and rewrites a
fresh draft to match. The pure logic lives in the analysis layer
(``backend/analysis/format_consistency.py``) and is reached through the workflow
toolkit; this package is the thin workflow binding (registration metadata +
the ``post_pipeline`` hook).

Unlike TTS, this workflow produces no byte artifacts and contributes no tools.
It gates on its own global config slot (``enabled``), defaulting on so it
preserves the prior always-run behaviour out of the box.
"""

from __future__ import annotations

from ..registry import Workflow

_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {
            "type": "boolean",
            "title": "Normalize RP markup to recent messages",
        },
    },
}

format_consistency_workflow = Workflow(
    id="format_consistency",
    display_name="Format Consistency",
    config_schema=_CONFIG_SCHEMA,
    config_defaults={"enabled": True},
)
