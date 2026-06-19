"""Format-consistency workflow.

A deterministic, no-LLM post-pipeline normalizer: it reads the dialogue /
narration markup convention of the recent assistant messages and rewrites a
fresh draft to match. The pure logic lives in the analysis layer
(``backend/analysis/format_consistency.py``) and is reached through the workflow
toolkit; this package is the thin workflow binding (registration metadata +
the ``post_pipeline`` hook).

Unlike TTS, this workflow produces no byte artifacts, contributes no tools, and
declares no config: its only setting was an on/off flag, now subsumed by the
framework per-workflow toggle, so suspension is the framework's job.
"""

from __future__ import annotations

from ..registry import Workflow

format_consistency_workflow = Workflow(
    id="format_consistency",
    display_name="Format Consistency",
)
