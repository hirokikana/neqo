# Contributing

Use Python 3.11 or newer and run `uv sync`. Before submitting a change:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

Keep engine-specific behavior in engine adapters. Add tests for changes in query
semantics, macro validation, metadata and completion. Tests must not need AWS
credentials or create remote resources by default. Never include credentials,
private queries, result datasets or local databases in contributions.

Describe the problem, resulting behavior, and validation in pull requests. Small,
focused changes are easier to review. Discuss API changes before large refactors.

Before a first push, review `git add --dry-run .`, then inspect the staged diff.
The root `neqo.yaml`, `neqo.local.yaml`, environment files, database files, CSV /
Parquet / Arrow outputs, and `exports/` are ignored. Keep rendered SQL outputs in
`exports/`; SQL files elsewhere may be intentional, versioned macros. Configuration
files under `examples/` are public samples: do not put private connection settings
there. `uv.lock` is intentionally versioned for reproducible development and CI.
Ignore patterns do not remove already tracked files or prevent `git add -f`.
