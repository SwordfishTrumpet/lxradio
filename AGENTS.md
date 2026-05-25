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
```

## Development commands

```bash
python run.py               # RECOMMENDED for dev: adds src/ to PYTHONPATH, always picks up source changes
uv run lxradio              # uses the installed copy in .venv — reinstall after source changes (see below)
uv pip install -e .         # reinstall in editable mode so uv run lxradio picks up source changes

uv run pytest tests/        # run tests
uv run pytest tests/ -k NAME # run single test
uv run ruff check src/ tests/  # lint
uv run mypy src/              # type check
```

**Note:** `uv run lxradio` resolves the package from `.venv/site-packages/`, not from `src/`. After editing source files, run `uv pip install -e .` or use `python run.py` which adds `src/` to `PYTHONPATH`. Tests always use source via the `pythonpath = ["src"]` setting in `pyproject.toml`.

**Note:** If `.env` contains `UV_NO_EDITABLE=1`, editable installs will silently fail. Remove that line or unset it in your shell.

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

### Player process lifecycle
- `Player.play()` catches `FileNotFoundError`, `PermissionError`, and other `OSError` subclasses from `subprocess.Popen`, passing a descriptive message to `_on_error` so the curses app does not crash.
- `Player.stop()` sets `_stop_requested = threading.Event()` before joining the metadata thread. `_read_output` checks the event inside its stdout loop and breaks promptly.

### DNS & API resilience
- `_resolve_host()` caches both successes (5 min TTL) and failures (30 sec TTL). A `_cached_failure` flag distinguishes the two states.
- `_get()` retries across fallback hosts (`_FALLBACK_HOSTS`) on network failure.
- **Click tracking** uses a dedicated `_click()` helper (not `_get()`) because `/url/{id}` returns a redirect rather than JSON.
- **Click deduplication**: `RadioApp._play_selected()` skips firing a new `report_click` thread if the same station was already reported within the last 3 seconds.

### Search performance
- `search()` uses a module-level `ThreadPoolExecutor(max_workers=2)` to fire `search_by_name` and `search_by_tag` concurrently. Worst-case latency drops from ~16s to ~8s.

## Coverage quirks

- `__main__.py` is omitted from coverage (`omit = ["*/__main__.py"]` in pyproject.toml).
- Some Linux-only volume control paths are skipped on macOS (see `test_player.py`).
