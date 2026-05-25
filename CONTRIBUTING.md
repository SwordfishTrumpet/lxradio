# Contributing to lxradio

Thanks for your interest in contributing!

## Development setup

No manual install step required — `uv` handles the environment automatically.

```bash
git clone https://github.com/anomalyco/lxradio
cd lxradio
uv run lxradio
```

## Running tests & linting

```bash
uv run pytest tests/          # run tests
uv run ruff check src/ tests/  # lint
uv run mypy src/              # type check
```

All three must pass before a PR is merged. CI runs on Python 3.10–3.13 on Ubuntu.

## Code style

- Python ≥ 3.10 with type annotations on public APIs.
- Use `threading.Lock` for cross-thread state.
- Atomic file writes via temp file + `os.replace()` for persistence.
- Catch specific exceptions; bare `except Exception: pass` is discouraged.
- Keep modules focused and small; the architecture is documented in `AGENTS.md`.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Make your changes with tests.
3. Ensure the full test suite passes locally.
4. Open a PR with a clear description of the problem and solution.

## Reporting bugs

Please use the bug report issue template and include your OS, Python version, mpv version, and lxradio version.
