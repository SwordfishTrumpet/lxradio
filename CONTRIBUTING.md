# Contributing to lxradio

Thanks for your interest in contributing!

## Development setup

No manual install step required — `uv` handles the environment automatically.

```bash
git clone https://github.com/SwordfishTrumpet/lxradio
cd lxradio
uv run lxradio
```

## Running tests & linting

```bash
uv run pytest tests/          # run tests
uv run ruff check src/ tests/  # lint
uv run mypy src/              # type check
```

All three must pass before a PR is merged. CI runs on Python 3.11–3.14 on Ubuntu.

## Code style

- Python ≥ 3.11 with type annotations on public APIs.
- Use `threading.Lock` for cross-thread state.
- Atomic file writes via temp file + `os.replace()` for persistence.
- Catch specific exceptions; bare `except Exception: pass` is discouraged.
- Keep modules focused and small; the architecture is documented in `AGENTS.md`.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Make your changes with tests.
3. Ensure the full test suite passes locally.
4. Open a PR with a clear description of the problem and solution.

## Releasing and rolling back

A release is a version bump, a tag, and a GitHub Release. It is done from `main` once CI is
green on the exact commit being shipped.

```bash
# 1. bump the version in pyproject.toml and src/lxradio/__init__.py, add a CHANGELOG entry
git commit -am "Release: v0.x.y — <summary>"
git tag -a v0.x.y -m "v0.x.y"
git push origin main
git push origin v0.x.y
gh release create v0.x.y --title v0.x.y --notes-file /tmp/notes.md
```

### When a release turns out to be bad

The trigger is any of: the published version cannot start, a defect worse than the previous
release is found, or a security problem ships with it. Decide between two recoveries before
doing either, and write the decision in the issue that tracks it.

**Withdraw the release** — use it when the version should not be installed at all. Deleting a
tag or a release does not remove copies people already downloaded, so the version number is
never reused.

```bash
gh release delete v0.x.y --yes        # remove the release page and its assets
git push origin :refs/tags/v0.x.y     # delete the tag on the remote
git tag -d v0.x.y                     # delete the tag locally
```

**Supersede it** — the default. Keep the tag, and publish a patch that fixes the problem, so
anyone who installed the bad version has somewhere to go.

```bash
git checkout main && git pull --ff-only
# fix the defect, then release normally as v0.x.(y+1)
```

Then tell users what to do. Add a note at the top of the new release body and a line under
`## Fixed` in CHANGELOG.md:

- What broke and which version has it, by version number.
- The version to upgrade to, and the one-line command: `uv tool upgrade lxradio` (or reinstall
  from the wheel of the new version).
- If the release was withdrawn, say that the version is gone and name the version to use
  instead.
- If the bad version is a security problem, follow SECURITY.md and use a GitHub Security
  Advisory rather than a plain release note.

## Reporting bugs

Please use the bug report issue template and include your OS, Python version, mpv version, and lxradio version.
