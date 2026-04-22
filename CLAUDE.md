# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Orb is an agentic roleplay frontend for LLMs. Single-page web app served by FastAPI on localhost, talks to any OpenAI-compatible LLM backend (author recommends Gemma 4; requires solid tool-calling + prompt-caching support). Each user message triggers a three-pass pipeline on a single model:

1. **Director** -- tool-calling pass that picks moods, plot direction, keywords, and optionally rewrites the user's message.
2. **Writer** -- generates the actual roleplay response (streamed).
3. **Editor** -- ReAct loop that surgically edits "slop" and enforces length guards. Detection is programmatic; the model only writes replacement sentences.

## Common commands

- `./run_unix.sh` -- install deps into `.venv`, launch uvicorn on :8899 (dev-reload).
- `./start_linux.sh` -- self-contained miniforge installer + launcher (isolated env under `./installer_files/`). `ORB_HOST` / `ORB_PORT` override defaults.
- `./scripts/tests.sh [pytest args]` -- runs pytest. E.g. `./scripts/tests.sh tests/unit/test_editor_loop.py -v` for a single file.
- `./scripts/lint.sh` -- flake8 on `backend/ tests/`.
- `./scripts/format.sh` -- black (Python) + biome (JS).
- `./scripts/security_check.sh` -- pip-audit + bandit.
- `./scripts/compatibility_test.sh` -- docker-based multi-Python test (3.9, 3.14).

`pytest.ini` sets `asyncio_mode = auto`, so all tests are implicitly async -- no `@pytest.mark.asyncio` needed.

## Architecture

### Pipeline coordinator -- `backend/orchestrator.py`

Public entry points: `handle_turn()` (new user message) and `handle_regenerate()` (retry an assistant message). Both yield SSE-style events `{"event": ..., "data": ...}`.

Events prefixed with `_` (`_result`, `_refined_result`) are **internal** -- consumed by `_consume_pipeline` for persistence and never forwarded to the client. Client-visible events: `director_start`, `reasoning`, `director_done`, `prompt_rewritten`, `token`, `writer_rewrite`, `editor_done`, `done`, `error`.

`_shielded_fallback` persists partial writer output if the stream is cancelled mid-generation. Reasoning-only output does NOT create a message node (only streamed `token` deltas count).

### KV cache reuse is load-bearing

The three-pass design's viability depends on the LLM caching the prefix across passes. Three things **must** stay identical across director/writer/editor calls:

- **Prefix** (system prompt + chat history) -- built once by `prompt_builder.build_prefix()` and reused.
- **Tool schemas** -- the union of enabled tools is computed once and sent on every pass. This is why `editor_rewrite` is mirrored into `enabled_tools` when length_guard is on (`orchestrator.py` near line 82) -- to keep the schema list identical.
- **Message ordering** -- only `tool_choice` and the trailing user message may vary per pass.

`backend/kv_tracker.py` tracks hit rates and logs a summary at the end of each pipeline. **Changing how the prefix, tool schemas, or message order is assembled can silently tank cache reuse without any test failing.** Verify `kv_tracker.log_summary()` output when touching these paths.

### Passes -- `backend/passes/`

- `director.py` -- tool-calling loop. Primary tool is `direct_scene` (see `tool_defs.py`), returning moods, keywords, plot_summary, next_event, writing_direction, detected_repetitions, user_intent.
- `writer.py` -- streams tokens for the roleplay response.
- `editor/` -- multi-file subpackage. `editor.py` is the ReAct driver. `slop_detector.py`, `opening_monotony.py`, `template_repetition.py`, `contrastive_negation.py` are programmatic audits. `audit.py` aggregates findings. The LLM only writes sentence replacements -- detection is code, not model.

### Data -- `backend/database.py` + `backend/migrations/`

aiosqlite; DB at `backend/data/app.db`. Migrations are append-only. To add one: create `backend/migrations/NNNN_description.py` with a `migrate(conn)` function, then append its module name to the `MIGRATIONS` list in `backend/migrations/__init__.py`. Each runs exactly once (tracked in `schema_migrations` table).

Messages form a **branching tree** via `parent_id`. Conversations track their `active_leaf_id`; swiping = switching which leaf is active. Don't assume flat history -- use `_get_path_to_leaf()` or `get_messages()` which walk the tree.

**Endpoints + model configs (save-slot storage).** Two normalized tables sit alongside the flat `settings` row:

- `endpoints(id, url, api_key)` -- saved backend connection slots.
- `model_configs(id, endpoint_id, model_name, system_prompt, temperature, min_p, top_k, top_p, repetition_penalty, max_tokens)` -- saved model configurations, each tied to one endpoint.

`settings.active_endpoint_id` / `settings.active_model_config_id` reference the currently-selected records. The flat `settings.endpoint_url` / `settings.api_key` / `settings.model_name` / hyperparam columns remain the **runtime source of truth** (what the orchestrator reads per request); the normalized tables are save slots the UI cascades to/from when the user switches between configurations. Dual-write: `update_settings()` writes the flat row, and the frontend `saveSetting()` cascade mirrors the change into the relevant `endpoints` / `model_configs` row via `syncEndpointRecord()` / `syncModelConfigRecord()`. CRUD helpers live in `database.py` (`get_endpoints`, `create_endpoint`, `update_endpoint`, `delete_endpoint`, `get_model_configs`, `create_model_config`, `update_model_config`, `delete_model_config`).

### Character cards -- `backend/tavern_cards.py`

Tavern Card v2 spec (PNG with base64 JSON in a `tEXt` chunk). Exported cards include an `orb_id` tag so re-importing relinks conversation history instead of creating a duplicate character.

### HTTP layer -- `backend/main.py`

Single FastAPI app. Frontend served as static files from `frontend/`. Streaming endpoints use `StreamingResponse` over SSE. `_active_clients` dict (keyed by conversation ID) tracks in-flight LLM generations so `/stop` can cancel them mid-stream.

Notable routes beyond the obvious CRUD:

- `/api/endpoints`, `/api/endpoints/{id}`, `/api/endpoints/{id}/models` -- endpoint save-slot CRUD.
- `/api/models/{id}` -- model-config save-slot update / delete.
- `POST /api/conversations/{cid}/continue` -- generate an assistant turn for the current user message **without** appending a new user message. Used when the frontend detects the last message is already a user turn (e.g. after edit-without-regen, or after an aborted prior generation). Internally calls `handle_turn(..., skip_user_persist=True)`.

### Frontend -- `frontend/`

Vanilla JS, no build step, no framework. `state.js` exports a single global `S` object mutated directly by other modules. `api.js` is the fetch wrapper (all calls are same-origin `/api/*`). `chat.js` handles message rendering + SSE stream parsing. `library.js` handles character management.

**Hybrid combobox (`settings.js`).** The `endpoint_url` and `model_name` settings fields render as "hybrid" inputs: a free-text field plus a dropdown of saved options (with per-item delete). A shared `initCombobox()` engine drives both. `saveSetting()` cascades: changing `endpoint_url` triggers `syncEndpointRecord()` (find or create an `endpoints` row, activate it, reload models); changing `model_name` triggers `syncModelConfigRecord()` (same pattern at the model_config level). Hyperparameter edits on the flat form flow through via `PUT /api/models/{id}`. Dropdown selection (`onHybridInput`) loads the chosen record's fields into the flat UI.

**User-message edit flow (`chat.js`).** `saveEdit()` is symmetric across roles -- it always does an in-place content update, never regenerates. If the user wants a fresh assistant response after editing, they use the Send / regenerate buttons on the adjacent assistant turn. `sendMessage()` detects when the last message is already a user turn and calls `/api/conversations/{cid}/continue` rather than creating a duplicate user message.

## Repo / branch layout

This clone is a **personal fork** of the GitHub upstream. `origin` points to `git@github.com:hpnyaggerman/Orb.git`; only one remote.

History: the project was originally hosted on GitLab, with `./scripts/mirror_to_gh.sh` maintaining a GitHub mirror under `origin-gh`. The original developer has since moved development to GitHub, dissolving the mirror relationship. `scripts/mirror_to_gh.sh` is **legacy** -- kept in the tree for historical reference but no longer part of the sync workflow. `origin-gh` no longer exists as a configured remote.

`nyagman-dev` is a personal dev-feature branch -- **not** an upstream PR branch. It's a rolling work tree where new features land; individual changes may later be cherry-picked onto dedicated PR branches when ready to propose upstream. Branched from `46a8554` ("compact chat UI") on the GitHub fork.
