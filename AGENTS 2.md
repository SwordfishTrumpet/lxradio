# AGENTS.md — lxradio

## Project overview

`lxradio` is a minimal terminal TUI radio player. It uses `curses` for the UI, `mpv` for audio playback, and the [radio-browser.info](https://www.radio-browser.info/) API for station data.

## Architecture

```
src/lxradio/
  __init__.py       — version info
  __main__.py       — CLI entry point (signal handlers)
  app.py            — curses TUI state machine (RadioApp)
  renderer.py       — pure curses drawing (Renderer, DrawState, StationRowLayout)
  key_dispatcher.py — registration-driven input handling (KeyDispatcher, KeyBinding)
  player.py         — mpv wrapper (Player)
  favorites.py      — persistent favourites manager (Favorites)
  history.py        — persistent listening log manager (History, HistoryEntry)
  radio_browser.py  — API client (Station, search, top stations)
  sleep_timer.py    — countdown timer with fade-out (SleepTimer)
```

## Development commands

```bash
python run.py                                  # RECOMMENDED for dev: always picks up source changes
uv run lxradio                                 # uses the installed copy in .venv
uv run lxradio -- --help                       # pass args through uv
uv pip install -e . && python fix_editable_install.py  # set up symlink-based editable install

uv run pytest tests/        # run tests
uv run pytest tests/ -k NAME # run single test
uv run ruff check src/ tests/  # lint
uv run mypy src/              # type check
```

**Note:** `uv run lxradio` resolves the package from `.venv/site-packages/`, not from `src/`. For development, `python run.py` adds `src/` to `PYTHONPATH` without needing any install.

**Note:** If `.env` contains `UV_NO_EDITABLE=1`, editable installs will silently fail. Remove that line or unset it in your shell.

**Symlink-based editable install (replaces .pth files):** The `fix_editable_install.py` script removes the `.pth` file that `uv pip install -e .` creates and replaces it with a symlink from `site-packages/lxradio` → `src/lxradio`. This avoids Python 3.14+ ignoring hidden `.pth` files on macOS, and avoids `.pth` file nonsense entirely.

```bash
uv pip install -e .          # creates dist-info and entry points
python fix_editable_install.py  # replaces .pth with symlink, no magic flags
```

After this, `uv run lxradio` picks up source changes immediately (no reinstall needed), and there are zero `.pth` files involved.

All three (test, lint, typecheck) must pass. CI runs on Python 3.10–3.13 on Ubuntu.

## Testing patterns

- **Tests mirror `src/` structure**: `tests/test_app.py` tests `src/lxradio/app.py`, etc.
- **Curses is mocked**: Most tests mock `curses` module and `RadioApp._scr` (a `MagicMock` with `getmaxyx.return_value = (24, 80)`).
- **Favorites and history files are monkeypatched**: Tests use `monkeypatch` to redirect `_FAVORITES_FILE`, `_HISTORY_FILE`, and `_CONFIG_DIR` to `tmp_path` to avoid touching real user config.
- **Player tests mock `subprocess` and `shutil.which`**.
- **Renderer tests mock `curses.window`** and test drawing helpers independently.

## Code conventions

- Python ≥ 3.10, type annotations on public APIs
- `threading.Lock` for cross-thread state (`app.py`, `player.py`)
- Atomic file writes via temp file + `os.replace()` (see `favorites.py`)
- Catch specific exceptions; bare `except Exception: pass` is discouraged
- Line length: 120 (ruff config)

## Key architectural rules

### Thread safety
- `RadioApp._lock` protects `_stations`, `_loading`, and `_status_msg` between main curses thread and background workers.
- `Player._lock` protects `_proc` and `_current_title`.
- **Callbacks are invoked *outside* the lock** (e.g. `on_metadata`, `on_error`) to avoid deadlock if the callback re-enters the object.

### Renderer immutability
- `RadioApp` builds an immutable `DrawState` dataclass on every frame and passes it to `Renderer.draw()`. The renderer never mutates app state. This makes drawing independently testable.

### KeyDispatcher
- Adding a new shortcut is one line: `d.register(KeyBinding(key, handler, description, when=...))`.
- Footer help text is auto-generated from the registry. The `when` predicate controls conditional display (e.g. volume controls only shown when `can_control_volume()` is true).

### Favourites durability
- Writes are atomic (`favorites.json.tmp` → `os.replace`).
- Corrupted files are backed up to `favorites.json.bak` and logged.
- Valid JSON that is not a list (e.g. `null`, dict, string) raises `TypeError` and is treated as corrupted.

### History durability
- Entries are stored as JSONL (`history.jsonl`) for append-only efficiency; each line is a self-contained JSON object.
- Cap at **1000 entries** — on load, oldest lines are trimmed if over limit.
- Writes are atomic (`history.jsonl.tmp` → `os.replace`).
- Corruption handling: a malformed **last line** is skipped with a warning; a malformed line in the middle or an entirely invalid file triggers a backup to `history.jsonl.bak` and a fresh start.
- `HistoryEntry` is an immutable `@dataclass(frozen=True)` with a `to_station()` helper so the renderer can treat history rows identically to station rows.

### Volume control
- **macOS**: mpv `--volume` at startup + IPC socket (`/tmp/lxradio-mpv-{pid}.sock`) for runtime changes. Volume is fully app-scoped.
- **Linux**: mpv IPC is attempted first; if the IPC socket is unavailable, falls back to `pactl set-sink-volume`. This may still affect global PulseAudio sink when mpv is not running.
- `_has_pactl()` caches its result in `_PACTL_AVAILABLE` to avoid ~150 filesystem syscalls/minute.

### Sleep timer
- Daemon thread counts down in 1s ticks; thread-safe `_remaining` and `_state` protected by `_lock`.
- Last 60s: fades mpv volume proportionally every 2s via the Player's `set_volume`. Fade catches `OSError` on IPC calls.
- `SleepTimer` accepts `get_volume`/`set_volume`/`on_expire` callables, keeping it decoupled from `Player`.
- Cancelled automatically when starting a new station (`_play_selected`) or stopping playback (`_space`).
- Presets cycle 15m → 30m → 60m → Off via `cycle_preset()`. Register `s`/`S` in `KeyDispatcher`.
- Countdown displayed in the now-playing bar (not header) alongside station name and volume.
- Session-only — no persistence between app restarts.

### Player process lifecycle
- `Player.play()` catches `FileNotFoundError`, `PermissionError`, and other `OSError` subclasses from `subprocess.Popen`, passing a descriptive message to `_on_error` so the curses app does not crash.
- `Player.stop()` sets `_stop_requested = threading.Event()` before joining the metadata thread. `_read_output` checks the event inside its stdout loop and breaks promptly.

### DNS & API resilience
- `_resolve_host()` caches both successes (5 min TTL) and failures (30 sec TTL). A `_cached_failure` flag distinguishes the two states.
- `_get()` retries across fallback hosts (`_FALLBACK_HOSTS`) on network failure.
- **Click tracking** uses a dedicated `_click()` helper (not `_get()`) because `/url/{id}` returns a redirect rather than JSON.
- **Click deduplication**: `RadioApp._play_selected()` skips firing a new `report_click` thread if the same station was already reported within the last 3 seconds.

### Search performance
- `search()` uses a module-level `ThreadPoolExecutor(max_workers=2)` to fire `search_by_name`, `search_by_tag`, and `search_by_country` concurrently. With 3 tasks on 2 workers, worst-case latency drops from ~24s (3 sequential 8s calls) to ~16s (2 rounds).

## Development cycle findings (2026-07-10)

### Mypy 2.1.0 hangs on Python 3.14
- Mypy 2.1.0 hangs indefinitely when checking packages with relative imports on Python 3.14.
- Upgrade to mypy **2.2.0** fixes this. `uv lock --upgrade-package mypy` then `uv sync`.

### `.venv` script shebangs break across directory moves
- `uv pip install` generates scripts with absolute shebang paths.
- If the project is moved (e.g. different mount path), scripts fail with `exec: .../python: cannot execute: No such file or directory`.
- Fix: `sed -i '' 's|/old/path/|/new/path/|g' .venv/bin/*`

### Race condition in `_build_draw_state` — two calls to `_history.all()`
- `Build_draw_state()` was calling `_current_stations()` (which internally calls `_history.all()`) and then building `history_timestamps` from a second `_history.all()` call.
- If the metadata thread added a history entry between the two calls, station entries and their timestamps desynchronized.
- **Fix:** Call `_history.all()` once, derive both stations and timestamps from the single result.

### Dependency upgrade pitfalls
- `uv pip install --upgrade PACKAGE` modifies `.venv` but NOT `uv.lock`.
- `uv lock --upgrade-package PACKAGE` updates the lock file.
- `uv lock --upgrade` upgrades ALL packages in lock file.
- Always use `uv lock --upgrade` then `uv sync` for proper dependency management.

### Python 3.14 ResourceWarnings from runtime (not our code)
- Running `pytest -W error::ResourceWarning` shows 6+ warnings from `tempfile.py:484` and `subprocess.py:1139`.
- These come from Python 3.14's `TemporaryFileCloser.__del__` and `Popen.__del__` during GC, triggered by pytest's internal infrastructure (not our source code).
- Traced with `subprocess.Popen` monkey-patching — no real Popen objects leak from our tests.
- Safe to ignore; these disappear without `-W all`.

## Coverage quirks

- `__main__.py` is omitted from coverage (`omit = ["*/__main__.py"]` in pyproject.toml).
- Some Linux-only volume control paths are skipped on macOS (see `test_player.py`).
