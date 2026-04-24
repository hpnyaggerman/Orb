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
- `./scripts/format_backend.sh` -- black (Python). `./scripts/format_frontend.sh` -- biome (JS).
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
- `editor/` -- multi-file subpackage. `editor.py` is the ReAct driver. `slop_detector.py`, `opening_monotony.py`, `template_repetition.py`, `contrastive_negation.py`, `structural_repetition.py` are programmatic audits. `audit.py` aggregates findings. The LLM only writes sentence replacements -- detection is code, not model.

### Data -- `backend/database.py` + `backend/migrations/`

aiosqlite; DB at `backend/data/app.db`. Migrations are append-only. To add one: create `backend/migrations/NNNN_description.py` with a `migrate(conn)` function, then append its module name to the `MIGRATIONS` list in `backend/migrations/__init__.py`. Each runs exactly once (tracked in `schema_migrations` table).

Messages form a **branching tree** via `parent_id`. Conversations track their `active_leaf_id`; swiping = switching which leaf is active. Don't assume flat history -- use `_get_path_to_leaf()` or `get_messages()` which walk the tree.

**Endpoints + model configs (save-slot storage).** Two normalized tables sit alongside the flat `settings` row:

- `endpoints(id, url, api_key, active_model_config_id)` -- saved backend connection slots. `active_model_config_id` remembers the last-used model per endpoint so switching endpoints restores that endpoint's chosen model.
- `model_configs(id, endpoint_id, model_name, system_prompt, temperature, min_p, top_k, top_p, repetition_penalty, max_tokens)` -- saved model configurations, each tied to one endpoint.

`settings.active_endpoint_id` references the currently-selected endpoint row; its `active_model_config_id` selects the currently-selected model config. The flat `settings.endpoint_url` / `settings.api_key` / `settings.model_name` / hyperparam columns remain the **runtime source of truth** (what the orchestrator reads per request); the normalized tables are save slots the UI cascades to/from when the user switches between configurations. Dual-write: `update_settings()` writes the flat row, and the frontend `saveSetting()` cascade mirrors the change into the relevant `endpoints` / `model_configs` row via `syncEndpointRecord()` / `syncModelConfigRecord()`. CRUD helpers live in `database.py` (`get_endpoints`, `create_endpoint`, `update_endpoint`, `delete_endpoint`, `get_model_configs`, `create_model_config`, `update_model_config`, `delete_model_config`).

**System prompt composition.** `settings.shared_system_prompt` is a global prompt; `model_configs.system_prompt` is per-model. `resolve_char_context()` in `database.py` combines them (shared first, then model-specific, `\n\n`-joined). A character card's `system_prompt`, if present, completely overrides both.

### Character cards -- `backend/tavern_cards.py`

Tavern Card v2 spec (PNG with base64 JSON in a `tEXt` chunk). Exported cards include an `orb_id` tag so re-importing relinks conversation history instead of creating a duplicate character.

### HTTP layer -- `backend/main.py`

Single FastAPI app. Frontend served as static files from `frontend/`. Streaming endpoints use `StreamingResponse` over SSE. `_active_clients` dict (keyed by conversation ID) tracks in-flight LLM generations so `POST /api/conversations/{cid}/stop` can cancel them mid-stream.

Notable routes beyond the obvious CRUD:

- `/api/endpoints`, `/api/endpoints/{id}`, `/api/endpoints/{id}/models` -- endpoint save-slot CRUD.
- `/api/models/{id}` -- model-config save-slot update / delete.
- `POST /api/conversations/{cid}/continue` -- generate an assistant turn for the current user message **without** appending a new user message. Used when the frontend detects the last message is already a user turn (e.g. after edit-without-regen, or after an aborted prior generation). Internally calls `handle_turn(..., skip_user_persist=True)`.
- `PUT /api/conversations/{cid}` -- rename a conversation (title edit).

### Backend request translation -- `backend/endpoint_profiles.py`

Some OpenAI-compatible backends reject unknown body fields (e.g. DeepSeek drops `min_p`, `top_k`, `repetition_penalty`) or reject forced tool_choice dicts when thinking is enabled. `endpoint_profiles.py` defines per-(endpoint_url, model) `ModelProfile` policies that mutate the request body before it leaves `LLMClient.complete()`. Two-level lookup: known endpoint + known model -> model-specific profile; known endpoint + blank model -> endpoint default; unknown endpoint -> pass-through. Typed knobs (`allow_extra`, `allow_forced_tool_choice`) cover common cases; `custom=` callables are the escape hatch.

### Frontend -- `frontend/`

Vanilla JS, no build step, no framework. `state.js` exports a single global `S` object mutated directly by other modules. `api.js` is the fetch wrapper (all calls are same-origin `/api/*`). `chat.js` handles message rendering + SSE stream parsing. `library.js` handles character management. `tabLock.js` uses `BroadcastChannel` to coordinate a single-writer lock across open tabs -- only the active tab can send; others are read-only to prevent racing edits. `mobile.js` + `mobile.css` drive the sub-900px responsive layout (burger menu, collapsible sidebar, mobile action dropdowns).

**Hybrid combobox (`settings.js`).** The `endpoint_url` and `model_name` settings fields render as "hybrid" inputs: a free-text field plus a dropdown of saved options (with per-item delete). A shared `initCombobox()` engine drives both. `saveSetting()` cascades: changing `endpoint_url` triggers `syncEndpointRecord()` (find or create an `endpoints` row, activate it, reload models); changing `model_name` triggers `syncModelConfigRecord()` (same pattern at the model_config level). Hyperparameter edits on the flat form flow through via `PUT /api/models/{id}`. Dropdown selection (`onHybridInput`) loads the chosen record's fields into the flat UI.

**User-message edit flow (`chat.js`).** `saveEdit()` is symmetric across roles -- it always does an in-place content update, never regenerates. If the user wants a fresh assistant response after editing, they use the Send / regenerate buttons on the adjacent assistant turn. `sendMessage()` detects when the last message is already a user turn and calls `/api/conversations/{cid}/continue` rather than creating a duplicate user message.

## Repo / branch layout

This clone is a **personal fork** of the GitHub upstream. `origin` points to `git@github.com:hpnyaggerman/Orb.git`; only one remote.

History: the project was originally hosted on GitLab, with `./scripts/mirror_to_gh.sh` maintaining a GitHub mirror under `origin-gh`. The original developer has since moved development to GitHub, dissolving the mirror relationship. `scripts/mirror_to_gh.sh` is **legacy** -- kept in the tree for historical reference but no longer part of the sync workflow. `origin-gh` no longer exists as a configured remote.

`nyagman-dev` is a personal dev-feature branch -- **not** an upstream PR branch. It's a rolling work tree where new features land; individual changes may later be cherry-picked onto dedicated PR branches when ready to propose upstream. Branched from `46a8554` ("compact chat UI") on the GitHub fork.

## Upstream sync workflow

Bringing `main` into `nyagman-dev` uses a **prep-then-merge** pattern. The goal is a clean before/after boundary: every change made in anticipation of the merge lands as its own commit on `nyagman-dev` first, then `git merge --no-ff main` brings main's SHAs in unchanged under a single merge commit. Main's commits remain reachable via `<merge-commit>^2`, so future branches can still fork off them.

Two rules govern everything below:

- **Main takes precedence, with one narrow exception.** Branch bends to main's shape by default. Every prep commit and every conflict resolution is an exercise in adapting branch to main's new direction. Branch-side design is preserved only in two cases: (a) the change is strictly additive and compatible with main -- both sides extend disjoint surfaces, and the interleave / union shortcut in Phase B applies; or (b) branch and main propose different solutions to the *same* problem and branch's solution is strictly technically superior (e.g. handles an edge case main's version misses, or carries a semantic guarantee main's lacks). Superiority is not a default assumption. It is a conclusion drawn only after explicit analysis of both solutions, and that analysis must be raised to the user before the branch-side resolution is committed. Anywhere else branch and main conflict, branch's version gets adapted or dropped, not preserved against main.
- **Design decisions require a user prompt.** Throughout prep and conflict resolution, choices routinely surface that have multiple reasonable shapes: which convention to promote to, how to adapt a function branch rewrote that main also rewrote, which of several valid interleaves to use, whether to drop a branch-side abstraction main has superseded. Any such choice that is not trivially obvious from main's shape alone must be put to the user before committing. Prompting is the default and mandatory behavior, not a fallback.

### Phase A: Prep commits

Start by reading main's commits since divergence. Inventory every change whose blast radius touches branch -- new or renamed files, schema changes, function signature changes, module splits or renames, naming conventions, and any logic branch also modified.

**Prep exists for the class of problems git's auto-merge cannot detect.** A 3-way textual merge catches overlapping edits to the same hunk; it does **not** catch semantic collisions where each side's edit is clean in isolation but the combined result breaks at runtime or violates the project's patterns. These bite after a green merge. Prep commits exist to preempt them.

Then, on branch and before the merge, land one commit per class of preemptive adaptation. The merge commit itself should be a mechanical interleave, not the place where design decisions happen under pressure.

Common prep categories:

1. **Collision resolution for sequentially-allocated identifiers.** Migration numbers, fixture IDs, enum slots -- any convention where both sides may have independently minted the same value. Rename branch's to the next free slot; confirm the runtime semantics of the rename (does the system key by name, number, or content hash?) and whether any already-recorded state needs reconciling.

2. **Normalize against main's conventions.** If branch carries an ad-hoc pattern main has since formalized (inline schema patches vs. formal migrations, per-call logging vs. a central logger, etc.), promote branch's version to match main's shape so the merged result is consistent.

3. **Pre-stage logic-conflict hotspots.** Functions both sides rewrote survive the textual merge but risk producing a Frankenstein mix. Where possible, rebase branch's change onto main's new shape pre-merge. Where not, note the location so Phase B's manual merge knows which side is the base.

4. **Signature and call-site adaptation.** If main renamed a symbol, changed a function signature, or moved a module, update branch's call sites now, not at merge time. Git will auto-merge cleanly and then crash at runtime.

5. **Refresh `CLAUDE.md`.** Read main's tree (`git show main:...`) and document its architectural additions plus any repo-layout changes. Grounds the prose in what actually landed.

6. **Run formatters last.** `./scripts/format_backend.sh` (black) + `./scripts/format_frontend.sh` (biome). Skipping this pollutes the merge-commit boundary with a trailing post-merge style commit.

### Phase B: Merge

```bash
git merge --no-ff main
```

Expect content conflicts in files both sides actively edited. Resolution follows the precedence rule above: where branch and main disagree on the *shape* of something, main wins and branch is bent to fit. The **interleave / take union** shortcut applies only to strictly additive conflicts -- both sides added real, disjoint content and both sides' additions should stay. Typical additive sites:

- Ordered lists in shared registries (migration list, route tables, plugin lists).
- Field sets in shared data structures (settings dicts, Pydantic models, allowed-keys lists, CREATE TABLE column lists, default-value maps).
- Guard blocks in shared init paths (inline ALTER guards, startup hooks, feature-flag switchboards).
- Adjacent code additions in the same module where both sides extended disjoint surfaces.

Manual merge is needed where both sides rewrote the same logic, and this is where the user-prompt rule matters most: if the "right" merged shape isn't obvious from main's side alone, stop and ask rather than guessing.

### Phase C: Verify

Run in order. The user pushes only after all pass; the agent does not push:

1. `./scripts/lint.sh` (flake8). `./scripts/format_backend.sh` + `./scripts/format_frontend.sh` -- should be a no-op post-Prep 4.
2. `./scripts/tests.sh` (full pytest). Integration tests covering main's new endpoints must pass.
3. Fresh-DB smoke: delete `backend/data/app.db`, start the server, verify `schema_migrations` contains every migration in order and any new seed rows land.
4. Server boot smoke: `curl` the canonical endpoints on both sides (branch's plus whichever routes main added).
5. Manual UI smoke: exercise the toggles and flows that branch and main each touched.

### History rewrite

Fixing already-committed work in place -- reword, remove a leaked secret, back out a debug change, change a conflict resolution, recover a bad commit or merge -- without re-doing manual conflict resolution or losing commit timestamps.

**Any history rewrite requires explicit user confirmation.** Before touching anything: present the plan (what is changing, which recipe from step 3, which commits are affected, the expected end state) and wait for the user to say go. Rewrites silently break downstream clones; the user owns that call.

**Invariants.** After the rewrite, relative to `backup/<label>` (step 1):
- The tree differs only by the intended delta.
- If the range contains a merge, `HEAD^2` still matches `main` hash-for-hash.
- Every commit's author-date and committer-date are unchanged.

**1. Tag before touching anything.** `git tag backup/<label> HEAD`. Originals stay reachable through this tag until step 6; without it, a bad `git reset` is unrecoverable.

**2. Pin both dates on every commit you create.** `git commit`, `git commit --amend`, and `git merge` reset committer-date to now; `git cherry-pick` and `git rebase` preserve author-date but still reset committer-date. Pin both explicitly:
```
AD=$(git log -1 --format=%aI <original-sha>)
CD=$(git log -1 --format=%cI <original-sha>)
GIT_AUTHOR_DATE="$AD" GIT_COMMITTER_DATE="$CD" git commit ...
```
The same env-var prefix goes in front of `git commit --amend` and `git merge --no-ff`. (`%aI`/`%cI` = ISO-8601 author/committer date.)

**3. Pick the recipe matching what you're changing.**

*Single non-merge commit* (reword or content edit):
```
git rebase -i --rebase-merges <base>        # mark the target `edit`
# at the stop:
orig=$(cat .git/rebase-merge/stopped-sha)
AD=$(git log -1 --format=%aI "$orig")
CD=$(git log -1 --format=%cI "$orig")
# content edit: modify files, git add.
# reword:      skip that, pass -m below.
GIT_AUTHOR_DATE="$AD" GIT_COMMITTER_DATE="$CD" \
  git commit --amend [-m "<new>"]
git rebase --continue
```

*Merge commit* (content fix, reword, or changed conflict resolution):
```
# capture the merge's dates before resetting:
AD=$(git log -1 --format=%aI <old-merge>)
CD=$(git log -1 --format=%cI <old-merge>)
git reset --hard <old-merge>^1              # branch tip right before the merge
GIT_AUTHOR_DATE="$AD" GIT_COMMITTER_DATE="$CD" \
  git merge --no-ff main -m "<msg>"
# on conflict: restore from backup (step 4), apply the fix, then
GIT_AUTHOR_DATE="$AD" GIT_COMMITTER_DATE="$CD" git commit
```

*Chain of commits* (bulk reword, purge a file from the range, apply a cross-commit patch):
```
git reset --hard <base>
for sha in $(git log <base>..backup/<label> --reverse --format=%H); do
  AD=$(git log -1 --format=%aI "$sha")
  CD=$(git log -1 --format=%cI "$sha")
  git cherry-pick --no-commit "$sha"
  # optional: modify files here before committing
  GIT_AUTHOR_DATE="$AD" GIT_COMMITTER_DATE="$CD" \
    git commit -m "<new message>"
done
```

Constraints that apply across recipes:
- `--rebase-merges` is mandatory whenever a merge is in the rewritten range; without it git flattens the merge and the `HEAD^2 == main` invariant breaks.
- For committer-date exactness across many commits, prefer the chain rewrite over `rebase -i`: rebase offers no hook on `pick`-only steps.
- `cherry-pick --no-commit` already inherits the source author; pinning `GIT_AUTHOR_DATE` on the follow-up `git commit` is belt-and-suspenders.

**4. If the replay re-hits original conflicts, restore from backup** rather than re-resolving by hand:
```
git checkout backup/<label> -- <conflicted-files>
git diff --check              # must exit 0 before the next commit
```
Staged restored blobs count as resolved.

**5. Verify before dropping the backup.** All of:
- `git diff backup/<label> HEAD` shows only the intended delta.
- If the range contains a merge: `git log <merge>^2` matches `git log main` hash-for-hash.
- Dates unchanged: `diff <(git log <base>..backup/<label> --format='%aI %cI') <(git log <base>..HEAD --format='%aI %cI')` must be empty.
- Tests, lint, format clean.
- Messages and files match the rewrite's intent. Example checks:
  ```
  git log <base>..HEAD --format='%B' | grep -iE '^(wip|fixup|squash)'  # no fixup leftovers
  git log <base>..HEAD --name-only | grep -F '<purged-file>'           # purged file is gone
  ```

**6. Finish.** `git tag -d backup/<label>`, and delete any stale `backup/*` tags left from earlier rewrites. **The agent never pushes; force or not.** Hand back with a clear summary and let the user run `git push --force-with-lease origin <branch>` themselves.

## Style: non-ASCII

Branch-owned content -- code, comments, docstrings, string literals, commit messages, and markdown -- must be ASCII-only. Standard replacements: em-dash `—` -> `--`, right arrow `→` -> `->`, box-drawing `═` -> `=`, ellipsis `…` -> `...`, curly quotes -> straight.

Don't touch main's non-ASCII. Characters that exist on main and appear on a branch-modified line (e.g. a non-ASCII char inside a UI template whose surrounding logic branch only gated) stay -- main owns them. The rule covers branch-introduced characters only.
