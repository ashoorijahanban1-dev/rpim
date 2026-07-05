# ADR 0001 — uv workspace, Python 3.12 pinned

**Status:** accepted (M0)

**Context.** CLAUDE.md mandates Python 3.12; the monorepo has three Python
apps + one shared package; the PostToolUse hook runs `make test` after every
edit, so dependency management must be fast and deterministic.

**Decision.** One uv workspace at the repo root: `members = ["apps/*",
"packages/*"]`, `exclude = ["apps/dashboard"]` (Node project). Python pinned
via `.python-version` = 3.12 and `requires-python >= 3.12`. The root project
depends on every member so `uv sync` installs the whole workspace. Rule: the
FIRST file written into a new member directory is its `pyproject.toml` —
a member dir without one breaks `uv run` for the entire workspace.

**Consequences.** `make test` = `uv run pytest` stays <1s warm. `uv.lock` is
committed. Docker images install per-package with
`uv sync --frozen --package <name>`.
