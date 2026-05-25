# AGENTS.md — lxradio

## Project overview

`lxradio` is a minimal terminal TUI radio player. It uses `curses` for the UI, `mpv` for audio playback, and the [radio-browser.info](https://www.radio-browser.info/) API for station data.

## Architecture

```
src/lxradio/
  __init__.py       — version info
  __main__.py       — CLI entry point (signal handlers)
  app.py            — curses TUI state machine (RadioApp, < 250 lines)
  renderer.py       — pure curses drawing (Renderer, DrawState, StationRowLayout)
  key_dispatcher.py — registration-driven input handling (KeyDispatcher, KeyBinding)
  player.py         — mpv wrapper (Player)
  favorites.py      — persistent favourites manager (Favorites)
  radio_browser.py  — API client (Station, search, top stations)
```

## Code conventions

- Python ≥ 3.10
- Type annotations on public APIs
- `threading.Lock` for cross-thread state (see `app.py`, `player.py`)
- Atomic file writes via temp file + `os.replace()` (see `favorites.py`)
- Bare `except Exception: pass` is discouraged; catch specific exceptions and log  
  **Current status**: 0 bare `except Exception` blocks remain. All previous violations in `app.py` (`_load_batch`), `player.py` (`stop`, `_mpv_ipc_set_volume`), and `radio_browser.py` (`_resolve_host`, `report_click`) have been fixed.

## Testing

- **Runner**: pytest
- **Coverage**: pytest-cov
- **Lint**: ruff
- **Type check**: mypy
- Tests live in `tests/` and mirror the `src/` structure.
- Use `uv run pytest tests/` to execute.

## Key implementation details

### Thread safety
- `RadioApp._lock` protects `_stations` and `_loading` between the main curses thread and background worker threads.
- `Player._lock` protects `_proc` and `_current_title`.
- **Callback discipline**: callbacks (e.g. `on_metadata`) are invoked *outside* the lock to avoid deadlock if the callback re-enters the object.

### DNS & API resilience
- `_resolve_host()` caches the resolved API host for 5 minutes (`_DNS_CACHE_TTL`). The module-level cache is protected by `threading.Lock()` for explicit thread safety.
- `_get()` retries across fallback hosts (`_FALLBACK_HOSTS`) on network failure.
- **Click tracking** uses a dedicated `_click()` helper, not `_get()`, because `/url/{id}` returns a redirect rather than JSON.
- **Click deduplication** in `RadioApp._play_selected()` skips firing a new `report_click` thread if the same station was already reported within the last 3 seconds (`_CLICK_DEBOUNCE_SECS`).

### Volume
- macOS: `mpv --volume` at startup + IPC socket (`/tmp/lxradio-mpv-{pid}.sock`) for runtime changes. Volume is fully app-scoped.
- Linux: mpv IPC is attempted first for runtime volume changes; only if the IPC socket is unavailable does it fall back to `pactl set-sink-volume`. This minimizes global PulseAudio sink disruption, though the fallback still affects system volume when mpv is not actively connected.
- `_has_pactl()` caches the result in a module-level `_PACTL_AVAILABLE: bool | None = None`. First call probes the filesystem; subsequent calls return the cached boolean, eliminating ~150 redundant filesystem syscalls per minute of use.
- `set_volume(0)` now sets `_muted = True`, so the UI consistently renders `MUTED` at zero volume. `volume_up()` from a muted state automatically unmute-restores to a low volume rather than the pre-mute volume.

### Favourites durability
- Writes are atomic (`favorites.json.tmp` → `os.replace`).
- Corrupted files are backed up to `favorites.json.bak` and logged.
- Load errors are caught as specific exceptions (`json.JSONDecodeError`, `OSError`, `KeyError`), not bare `Exception`.
- **Edge case** (resolved): valid JSON that is not a list (e.g. `null`, a dict, or a string) is now caught by an explicit `isinstance(data, list)` check that raises `TypeError`, which the outer `except` block catches alongside `json.JSONDecodeError`, `OSError`, and `KeyError`. The corrupted file is backed up to `favorites.json.bak` and the app starts with an empty favourites list.

### Logging
- `logging.basicConfig()` is set up in `__main__.py:main()` at `WARNING` level so library log messages (e.g. corrupted favourites) are visible to users.

### Player process spawning
- `Player.play()` catches `FileNotFoundError`, `PermissionError`, and other `OSError` subclasses from `subprocess.Popen`, passing a descriptive message to `_on_error` so the curses app does not crash.

### Renderer architecture
- `Renderer` is instantiated once in `_main()` and receives a `curses.window` handle.
- `RadioApp` builds an immutable `DrawState` dataclass on every frame and passes it to `Renderer.draw()`. The renderer never mutates app state.
- `StationRowLayout` (a `NamedTuple`) replaces magic column constants. `compute_layout(w)` returns a single layout object that includes `show_details = False` on narrow terminals, eliminating the abrupt `if w < 60: return` guard clause.
- Drawing helpers (`_trunc`, `_vol_bar`, `_safe_addstr`, `_dim`, `_SPINNER`) live in `renderer.py` and are independently testable with a mocked `scr`.

### KeyDispatcher
- `KeyDispatcher` maps key codes to handlers via a registry of `KeyBinding` objects.
- Each binding stores: `key` (int or tuple), `handler` (`Callable[[RadioApp], bool | None]`), `description` (for footer generation), and an optional `when` predicate for conditional bindings (e.g. volume controls only shown when `can_control_volume()` is true).
- The footer help text is generated dynamically from the registry, eliminating the previously hardcoded string.
- Adding a new shortcut is one line of registration.

### Player thread lifecycle
- `Player.stop()` sets a `_stop_requested = threading.Event()` before joining the metadata thread. `_read_output` checks the event inside its `for line in proc.stdout:` loop and breaks promptly, ensuring threads terminate deterministically within milliseconds rather than waiting for the next stdout line.

### DNS resilience
- `_resolve_host()` caches both successes (5 min TTL) and failures (30 sec TTL). A `_cached_failure` flag distinguishes the two states. During a transient DNS outage, repeated calls fall back immediately instead of stalling on repeated `socket.getaddrinfo()` attempts.

### Search performance
- `search()` uses a module-level `ThreadPoolExecutor(max_workers=2)` to fire `search_by_name` and `search_by_tag` concurrently. Worst-case latency drops from the sum of the two round-trips to the slower of the two.

### Tag handling
- `Station.from_api()` now stores **all** tags (no truncation at parse time).
- `tag_str(max_tags=4)` handles display truncation. Downstream logic can access the full tag list for filtering or future tag-cloud features.

### Hardened `_safe_addstr`
- Only suppresses `curses.error` when `x + len(s) > w` (the expected narrow-terminal case). All other curses errors are logged as `WARNING` with `y, x, w, s[:20]` so layout bugs surface during development.

### Event loop testability
- `_main()`'s loop body is extracted into `_tick(key: int) -> bool`. `_main` becomes a thin wrapper: `while not self._tick(stdscr.getch()): ...`
- `_tick` is unit-tested with synthetic key inputs without needing a real terminal.

### Graceful shutdown
- `RadioApp.shutdown()` stops the player and clears pending loaders. `__main__.py` calls this public method instead of reaching into `app._player.stop()`.
- `SIGINT`/`SIGTERM` handlers in `__main__.py` call `app.shutdown()` before exiting.

## WCAG 2.2 AA considerations for TUI
- Ensure text contrast: `C.DIM` uses `curses.A_DIM` for visible dimming.
- Provide clear status messages for all user actions (add/remove favourite, errors, loading).
- Support narrow terminals: `name_w` is clamped to `max(0, min(30, w - 30))` and `_safe_addstr` gracefully suppresses only the expected overflow.
