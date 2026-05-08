# AGENTS.md — Orb Codebase Guide

## Project Overview

Orb is an **agentic AI roleplay/writing frontend** with a Python/FastAPI backend and a vanilla JS frontend. It orchestrates multi-pass LLM pipelines (Director → Writer → Editor) with tool-calling agents that control scene direction, rewrite prompts, audit output quality, and enforce length constraints. Characters are imported as PNG cards (V2 spec). Conversations support branching (swipes), lorebooks, mood fragments, and user personas.

**Stack:** Python 3.11+, FastAPI, aiosqlite, vanilla JS (no framework), SQLite DB, uvicorn

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (vanilla JS)                     │
│  state.js ←→ api.js ←→ SSE streaming ←→ chat.js (rendering)    │
│  Inspector panel: moods, reasoning, tool calls, injection block  │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP + SSE
┌───────────────────────────────┴─────────────────────────────────┐
│                     Backend (FastAPI + SQLite)                    │
│                                                                   │
│  handle_turn() in orchestrator.py                                 │
│    │                                                              │
│    ├── [Pre-Writer] Prompt Rewriter (optional)                    │
│    │     Rewrites vague user messages into richer input            │
│    │                                                              │
│    ├── Director Pass (passes/director.py)                         │
│    │     LLM calls direct_scene tool → fills fragments            │
│    │     Returns: moods, plot_summary, keywords, next_event,       │
│    │             writing_direction, response_length, etc.          │
│    │                                                              │
│    ├── Writer Pass (passes/writer.py)                             │
│    │     Main generation pass. System prompt + history +           │
│    │     Scene Direction injection block + user message.            │
│    │     Streams response tokens via SSE.                          │
│    │                                                              │
│    └── [Post-Writer] Editor Pass (passes/editor/) (optional)      │
│          Checks: slop detection, banned phrases, repetitive        │
│          openers/templates, structural repetition, length guard.   │
│          Tools: editor_apply_patch or editor_rewrite.              │
│          Up to 3 iterations.                                       │
│                                                                   │
│  Pipeline context built by _load_pipeline_context() →              │
│    _build_prefix_from_ctx() → build_prefix() in prompt_builder.py │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
Orb/
├── backend/
│   ├── main.py              # FastAPI app: all API routes, Pydantic models
│   ├── orchestrator.py      # Pipeline orchestration: handle_turn, _run_pipeline
│   ├── database.py          # All DB operations (aiosqlite), migrations, seed data
│   ├── llm_client.py        # LLM API client (OpenAI-compatible), streaming, reasoning
│   ├── prompt_builder.py    # System prompt assembly, style injection, lorebook injection
│   ├── tool_defs.py         # Tool schemas (direct_scene, rewrite, editor tools), constants
│   ├── endpoint_profiles.py # Per-provider quirks (url patterns, body transforms)
│   ├── tavern_cards.py      # PNG card import (tEXt chunk extraction, V2 spec parsing)
│   ├── kv_tracker.py        # Debug: logs messages/tools to JSON for inspection
│   ├── passes/
│   │   ├── director.py      # Director pass: LLM calls direct_scene tool
│   │   ├── writer.py        # Writer pass: main streaming generation
│   │   └── editor/
│   │       ├── editor.py    # Editor orchestrator: audit → patch/rewrite loop
│   │       ├── audit.py     # Phrase bank matching, opener/template detection
│   │       ├── slop_detector.py       # Regex-based banned phrase detection
│   │       ├── opening_monotony.py    # Repetitive sentence opener detection
│   │       ├── template_repetition.py # Part-of-speech pattern repetition
│   │       ├── structural_repetition.py # Same paragraph layout as previous msgs
│   │       └── contrastive_negation.py # "not X, but Y" cliché detection
│   ├── migrations/          # 12 DB migrations (0001–0012)
│   └── data/                # Runtime: app.db (SQLite), orb.log
├── frontend/
│   ├── index.html           # Single-page app shell
│   ├── app.js               # Bootstrap: wire up sidebar, tabs, modals
│   ├── state.js             # Global state object (S.*), reactive getters
│   ├── api.js               # All fetch() calls to backend
│   ├── chat.js              # Chat rendering, message display, Inspector, streaming
│   ├── library.js           # Character card grid/list, CRUD UI
│   ├── settings.js          # Settings panel, endpoint/model config UI
│   ├── lorebooks.js         # World/lorebook entry management
│   ├── modal.js             # Generic modal utilities
│   ├── mobile.js            # Mobile-specific handlers
│   ├── utils.js             # $() helper, esc(), debounce, etc.
│   ├── validate.js          # Input validation helpers
│   ├── tabLock.js           # Browser tab visibility lock
│   ├── style.css            # Main stylesheet
│   ├── mobile.css           # Mobile breakpoints
│   ├── fonts.css            # Custom font declarations
│   └── themes/              # 8 CSS theme files (dark, christmas, etc.)
├── tests/
│   ├── unit/                # 9 unit test files
│   └── integration/         # 7 integration test files (FastAPI TestClient)
├── scripts/
│   └── dump_diagnostic.py   # DB state dump for debugging
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Database Schema

### Core Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `settings` | Global singleton config (id=1) | endpoint_url, model_name, enabled_tools (JSON), length_guard_*, reasoning_enabled_passes, active_persona_id, active_endpoint_id |
| `endpoints` | LLM API endpoints | url, api_key, active_model_config_id → model_configs.id |
| `model_configs` | Per-endpoint model settings | endpoint_id → endpoints.id, model_name, temperature, top_p, top_k, min_p, repetition_penalty, max_tokens, system_prompt |
| `conversations` | Chat sessions | character_card_id, character_name, character_scenario, first_mes, post_history_instructions, active_leaf_id → messages.id |
| `messages` | All messages (supports branching) | conversation_id, role (user/assistant), content, turn_index, swipe_index, is_active, parent_id → messages.id (tree structure) |
| `character_cards` | Imported/created characters (V2 spec) | name, description, personality, scenario, first_mes, mes_example, system_prompt, avatar_b64, world_id → worlds.id |
| `user_personas` | User profiles injected into system prompt | name, description, avatar_color |

### Agent/Auditor Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `director_state` | Per-conversation Director memory | conversation_id (PK), active_moods (JSON), keywords (JSON) |
| `director_fragments` | Dynamic Director parameters | id (PK), label, description, field_type, required, enabled, injection_label, sort_order |
| `mood_fragments` | Named mood presets | id (PK), label, description, prompt_text, negative_prompt, enabled |
| `phrase_bank` | Banned phrases for editor audit | id, variants (JSON array of strings) |
| `conversation_logs` | Per-turn Director audit trail | conversation_id, turn_index, agent_raw_output, tool_calls (JSON), active_moods_after, injection_block, agent_latency_ms |

### World/Lorebook Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `worlds` | Lorebook containers | name, enabled |
| `lorebook_entries` | Keyword-triggered context injections | world_id, name, content, keywords (JSON), case_insensitive, priority, enabled |

### Supporting Tables

| Table | Purpose |
|-------|---------|
| `message_attachments` | Images attached to messages (mime_type, data_b64) |

### Relationships

```
endpoints 1──N model_configs
endpoints 1──1 settings (active_endpoint_id)
model_configs 1──1 endpoints (active_model_config_id)
settings 1──1 user_personas (active_persona_id)
conversations N──1 character_cards
conversations 1──N messages (tree via parent_id)
conversations 1──1 director_state
conversations 1──N conversation_logs
messages 1──N message_attachments
character_cards N──1 worlds
worlds 1──N lorebook_entries
```

## API Endpoints

### Settings & Config
- `GET /api/settings` / `PUT /api/settings` — Global settings singleton
- `GET /api/endpoints` / `POST /api/endpoints` — List/create endpoints
- `GET/PUT/DELETE /api/endpoints/{id}` — CRUD single endpoint
- `GET/POST /api/endpoints/{id}/models` — List/create model configs
- `PUT/DELETE /api/models/{id}` — Update/delete model config

### Conversations
- `GET /api/conversations` / `POST /api/conversations` — List/create
- `PUT/DELETE /api/conversations/{cid}` — Update/delete
- `POST /api/conversations/{cid}/touch` — Update timestamp
- `POST /api/conversations/{cid}/summarize` — SSE stream narrative summary
- `POST /api/conversations/{cid}/compress` — Create compressed continuation
- `POST /api/conversations/{cid}/stop` — Abort generation

### Messages
- `GET /api/conversations/{cid}/messages` — Full message tree
- `POST /api/conversations/{cid}/send` — Send message (SSE stream response)
- `POST /api/conversations/{cid}/continue` — Regenerate from last user msg
- `POST .../messages/{id}/edit` — Edit message content
- `DELETE .../messages/{id}` — Delete message + descendants
- `POST .../messages/{id}/switch-branch` — Switch active branch
- `POST .../messages/{id}/regenerate` — Regenerate single response
- `POST .../messages/{id}/super_regenerate` — Regenerate keeping prior as context
- `POST .../messages/{id}/magic_rewrite` — Rewrite with custom instruction

### Characters
- `GET /api/characters` / `POST /api/characters` — List/create
- `POST /api/characters/import` — Import from PNG (multipart upload)
- `GET/PUT/DELETE /api/characters/{id}` — CRUD
- `GET /api/characters/{id}/avatar` — Serve avatar image
- `GET /api/characters/{id}/export` — Export as PNG card

### Fragments & Moods
- `GET/POST/PUT/DELETE /api/fragments` — Mood fragments CRUD
- `GET/POST/PUT/DELETE /api/director-fragments` — Director fragments CRUD

### Worlds & Lorebooks
- `GET/POST/PUT/DELETE /api/worlds` — Worlds CRUD
- `GET/POST/GET/PUT/DELETE /api/worlds/{id}/entries` — Lorebook entries CRUD
- `POST /api/worlds/{id}/import` — Import lorebook from character card

### Personas
- `GET/POST /api/user-personas` — List/create
- `PUT/DELETE /api/user-personas/{id}` — Update/delete

### Inspector
- `GET /api/conversations/{cid}/director` — Director state
- `GET /api/conversations/{cid}/logs` — Conversation logs

### Other
- `GET /api/themes` — Available CSS themes
- `POST /api/reset` — Factory reset (confirm required)

## Configuration Chain

```
settings.active_endpoint_id → endpoints[id]
    endpoints.active_model_config_id → model_configs[id]
        model_configs: model_name, temperature, top_p, top_k, min_p, 
                       repetition_penalty, max_tokens, system_prompt
    endpoints: url, api_key
settings.enabled_tools → {"direct_scene": true, "rewrite_user_prompt": false, ...}
settings.reasoning_enabled_passes → {"director": true, "writer": false, "editor": false}
settings.active_persona_id → user_personas[id]
```

The model config system allows multiple configs per endpoint. The active one is selected via `endpoints.active_model_config_id`.

## Frontend Architecture

- **State** (`state.js`): Single global `S` object. No reactive framework — components call `render*()` functions after state mutations.
- **Rendering** (`chat.js`): `renderMessages()` rebuilds the entire message list from `S.messages`. Inspector panel rendered by `renderInspector()`.
- **Streaming**: SSE events (`token`, `_result`, `_error`, `done`) parsed in `chat.js`. Tokens accumulate into the current message div in real-time.
- **API** (`api.js`): All backend calls via `fetch()`. SSE streams handled by `EventSource`-like parsing in `chat.js`.
- **Branching**: Messages have `parent_id` forming a tree. `swipe_index` + `is_active` select the visible branch. UI shows swipe dots.

## Context Management

Orb sends the **full conversation history** every turn — no automatic truncation or rolling window.

- `updateContextCounter()` estimates tokens as `chars / 3.5` (rough)
- **Manual compress flow**: `POST /summarize` → LLM writes narrative summary → user reviews → `POST /compress` → creates new conversation with summary + last N messages
- No RAG, no background compaction, no automatic summarization

## Testing

- **Unit tests** (`tests/unit/`): Test individual functions — editor audit, fragment parsing, dialogue splitting, template detection, abort logic.
- **Integration tests** (`tests/integration/`): FastAPI `TestClient` against real DB — CRUD for characters, conversations, endpoints, settings, fragments, personas.
- **Run**: `cd ~/repos/Orb && python -m pytest tests/ -v`
- **No e2e tests** for the frontend.

### Codex Sandbox Caveat

When running under Codex's filesystem/network sandbox, `aiosqlite` integration tests can hang before the first test body runs. The sandbox stalls `sqlite3.connect()` when it is executed from `aiosqlite`'s worker thread. This is a Codex execution-environment limitation, not an Orb database bug.

- Unit tests that do not initialize the async DB can run normally in the sandbox.
- Integration tests, app startup checks, and any command calling `backend.database.init_db()` should be run with Codex escalated execution (`sandbox_permissions: "require_escalated"`).
- Details and reproduction: `docs/codex-sandbox.md`.

## Common Development Workflows

### Adding a New Director Fragment

1. `POST /api/director-fragments` with `id`, `label`, `description`, `field_type`, `required`, `enabled`, `injection_label`, `sort_order`
2. The fragment is automatically included in the `direct_scene` tool schema via `build_direct_scene_tool()` in `tool_defs.py`
3. The Director LLM fills the field, it gets injected into the writer prompt via `build_style_injection()` in `prompt_builder.py`

### Adding a New Pipeline Pass

1. Create `backend/passes/your_pass.py` — follow the pattern of `director.py` or `writer.py`
2. Add tool schemas to `tool_defs.py` if the pass uses tool calling
3. Integrate into `_run_pipeline()` in `orchestrator.py`
4. Add SSE events for streaming output
5. Handle in frontend `chat.js` event parser

### Adding a New Tool

1. Define the tool schema in `tool_defs.py` (OpenAI function-calling format)
2. Register in `TOOLS` dict with `choice` and `schema` entries
3. Add to `PRE_WRITER_TOOLS` or `POST_WRITER_TOOLS` sets
4. Handle the tool call response in the relevant pass
5. Add toggle in `settings.enabled_tools` and frontend tools panel

### Adding a New UI Panel

1. Add HTML structure to `index.html`
2. Add toggle button with `onclick` handler
3. Create `renderYourPanel()` function in the relevant JS file
4. Wire into state updates (call `renderYourPanel()` after mutations)

## Gotchas and Pitfalls

1. **No auto-context-compaction** — Conversations grow unbounded until the user manually triggers summarize+compress. Long conversations will eventually exceed the model's context window.

2. **Full history sent every turn** — `get_messages()` returns everything. No sliding window or token budget management in the pipeline.

3. **Message tree branching** — Messages use `parent_id` to form a tree. `is_active` marks the visible branch. `swipe_index` selects among siblings. Deleting a message cascades to all descendants.

4. **Streaming lifecycle** — SSE connections must be properly cleaned up. The `_CleanupStreamingResponse` wrapper handles client disconnects. The `stop` endpoint sets an abort flag checked between pipeline stages.

5. **Tool call parsing** — The Director pass parses JSON tool call arguments. Malformed JSON from the LLM can crash the pipeline. Error handling wraps these in try/except but edge cases exist.

6. **SQLite + aiosqlite** — All DB operations are async via aiosqlite. No ORM — raw SQL in `database.py`. Migrations run sequentially by number prefix.

7. **Endpoint profiles** — Different LLM providers need different request bodies. `endpoint_profiles.py` handles URL detection and body transformation. Adding a new provider may require a new profile.

8. **Reasoning models** — Some models (GLM-5.x, DeepSeek) emit `reasoning_content` before `content`. The streaming handler separates these. `reasoning_enabled_passes` in settings controls which pipeline passes get reasoning enabled.

9. **Migrations are sequential** — New migrations must use the next number in sequence. They run at app startup via `_run_migrations()`.

10. **Phrase bank format** — `phrase_bank.variants` is a JSON array of strings. The editor audit matches these against response text using case-insensitive regex.

11. **Lorebook scan depth** — Hard-coded to 6 messages (`LOREBOOK_SCAN_DEPTH` in `prompt_builder.py`). Only the last 6 messages are scanned for lorebook keyword matches.

12. **`updateContextCounter()` is approximate** — Token estimate is `chars / 3.5`, doesn't include system prompt, persona, scenario, director injection, or lorebook blocks.
