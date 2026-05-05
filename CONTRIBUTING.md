# Contributing to Orb

Thanks for wanting to contribute. Here's what to do before opening a PR.

## 1. Get things running locally

Make sure the feature or fix works first.

Start the backend with `./run_unix.sh` (or `run_windows.bat` on Windows). Python 3.9+ required.

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

- Small models first. If it doesn't work on something like Gemma 4 26B, it probably doesn't belong here.
- Don't add agentic tools unless you really need them.
- Keep the agent's scope tight - less freedom, fewer hallucinations.
- Prefer algorithmic scanning over making the LLM eyeball things.
