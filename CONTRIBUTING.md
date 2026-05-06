# Contributing to Orb

Thanks for wanting to contribute. Here's what to do before opening a PR.

## 1. Get things running locally

Make sure the feature or fix works first.

Start the backend with `./run_unix.sh` (or `run_windows.bat` on Windows). Python 3.9+ required.

### Optional: Auto-formatting on commit

Run `npm install` to set up git hooks via Lefthook. This auto-formats staged files before each commit:

- **Python** — Black (formatting) + Flake8 (linting)
- **JavaScript** — Biome (formatting)

No more CI failures from formatting issues. Requires Node.js.

## 2. Run the checks

Everything lives in `scripts/`. Run them before you push:

- **Tests** - `./scripts/tests.sh all`
- **Format** - `./scripts/format_backend.sh` and `./scripts/format_frontend.sh`
- **Lint** - `./scripts/lint.sh`
- **Compatibility** - `./scripts/compatibility_test.sh`

If any of these fail, fix it before submitting.

## 3. Open a PR

- Keep it focused. One feature or fix per PR.
- Write a summary in the PR description that explains the what and the why.
- Link any related issues.

## Quick rules

- Small models first. If a feature doesn't work on something like Gemma 4 26B4A, it probably doesn't belong here.
- Only use agentic functionalities when absolutely needed - we will not have useless tools like `dice_roll`
- Keep the agent's scope tight - less freedom, fewer hallucinations.
- If something can be done with an algorithm, don't use an LLM for it.
- AI-generated code is accepted. It will be manually reviewed just like human written code. But must be subjected to more testing.
