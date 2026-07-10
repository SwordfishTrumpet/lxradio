# TODO

## Completed (lxradio v0.1.0+)

### ✅ Persistent Listening History with Song Timeline
All 7 phases of the history feature are implemented, tested, and passing:
- `history.py` with `HistoryEntry` (frozen dataclass), JSONL persistence, 1000-entry cap, atomic writes, corruption recovery
- `Player.play()` accepts `Station` object and emits `on_history` events on playback start and metadata change
- `RadioApp` has `View.HISTORY`, history callback integration, station cache for metadata lookup
- `Tab` key cycles BROWSE → FAVORITES → HISTORY → BROWSE
- Renderer shows relative timestamps in history view, "No listening history yet." empty state
- Comprehensive test coverage: history module, app integration, player callbacks, renderer display

### ✅ Dependency Upgrades (2026-07-10)
- `mypy` 2.1.0 → 2.2.0 (fixed Python 3.14 compatibility hang)
- `pytest` 9.0.3 → 9.1.1
- `ruff` 0.15.14 → 0.15.21
- `coverage` 7.14.0 → 7.15.0
- `ast-serialize` 0.5.0 → 0.6.0
- `librt` 0.11.0 → 0.13.0
- `typing-extensions` 4.15.0 → 4.16.0

### ✅ Bug Fix: Race condition in `_build_draw_state`
**File:** `src/lxradio/app.py`
**Bug:** `_build_draw_state` called `_history.all()` twice — once in `_current_stations()` and once for `history_timestamps`. If another thread added a history entry between the two calls, station entries and their timestamps could get out of sync.
**Fix:** Call `_history.all()` once, derive both stations and timestamps from the single result.

### ✅ Infrastructure Fixes
- Fixed broken `.venv` script shebangs (pointed to wrong path missing `Code/Projects/`)

---

## Known Issues (Low Priority)

### Sleep timer fade off-by-one
**Files:** `src/lxradio/sleep_timer.py`
**Detail:** When the timer enters the fade zone at ~60s, `fade_start_remaining` is captured after decrementing by 1, so the fade duration is 59s instead of 60s. The volume may not reach exactly 0 by the time the timer expires. Minor — `on_expire` kills mpv anyway.

### `format_time_ago` future timestamps
**File:** `src/lxradio/renderer.py`
**Detail:** `format_time_ago(timestamp)` returns "now" when `timestamp > time.time()` (negative diff). Acceptable for current usage (history entries always have past timestamps).

### `fix_editable_install.py` hardcoded Python version
**File:** `fix_editable_install.py`
**Detail:** Path hardcodes `python3.14` — will break on Python 3.15+. Low priority as this is a dev-only utility script.
