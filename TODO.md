# TODO.md — lxradio Roadmap to All-A Rating

_Target: bring every architectural aspect to an A rating._

Current baseline (post-audit): Modularity B+, Thread safety A, Error handling B+, Testability B, Type safety A, Performance B, Maintainability B.

---

## 1. Modularity → A

### 1.1 Extract `Renderer` from `RadioApp`
**File**: `src/lxradio/app.py` (506 lines → target < 250)
**Problem**: `RadioApp` is a god class that mixes state management, input handling, pagination, and ~200 lines of curses drawing. This makes the drawing code impossible to test without instantiating the entire app, and any visual change requires touching the same file as business logic.
**Plan**:
1. Create `src/lxradio/renderer.py` with a `Renderer` class.
2. `Renderer` owns `_setup_colors`, `_draw`, `_draw_header`, `_draw_search_bar`, `_draw_station_list`, `_draw_station_row`, `_draw_now_playing`, `_draw_footer`.
3. `Renderer` receives a `curses.window` handle and a read-only view model (e.g., a `DrawState` dataclass or typed dict) from `RadioApp`. It never mutates state.
4. `_safe_addstr`, `_trunc`, `_vol_bar`, `_dim`, `_SPINNER` move to `renderer.py` or a `drawing.py` module.
5. `RadioApp` delegates: `self._renderer.draw(self._build_draw_state())`.
6. **Result**: `app.py` contains only event loop, input handling, state transitions, and loader orchestration. `renderer.py` is pure drawing and testable with a mocked `scr`.

### 1.2 Extract `KeyDispatcher`
**Problem**: `_handle_nav_key` is a 70-line `if/elif` chain with mixed concerns (navigation, playback, view switching, volume, favourites, search entry). Adding a new keybinding means editing this chain and risking off-by-one errors in the `elif` logic.
**Plan**:
1. Create a `KeyBinding` dataclass: `key: int | tuple[int, ...]`, `handler: Callable[[RadioApp], bool | None]`, `description: str`.
2. Register bindings in a `KeyDispatcher` that maps key codes to handlers.
3. Handlers are small functions or methods on `RadioApp` that return `True` for quit, `False`/`None` for continue.
4. The footer help text is generated from the dispatcher registry, eliminating the hardcoded footer string.
5. **Result**: Adding a key is one line of registration. The dispatcher is independently testable.

---

## 2. Thread safety → A (maintain)

### 2.1 Fix `_load_batch` worker writing `_status_msg` outside the lock
**File**: `src/lxradio/app.py:463-465`
**Problem**: The worker thread sets `self._status_msg = f"Error: {e}"` without acquiring `_lock`. The main thread reads it during `_draw_now_playing()`. In CPython this is usually safe for string references, but it is a formal data race and may produce torn strings or stale reads on other implementations.
**Plan**:
1. Change the worker to set `_status_msg` inside the `with self._lock:` block at line 466, or use a `queue.Queue` for one-way status message delivery from worker to main thread.
2. **Result**: Eliminates the only remaining unsynchronized cross-thread write in the codebase.

---

## 3. Error handling → A

### 3.1 Harden `_safe_addstr` against silent bug masking
**File**: `src/lxradio/app.py:47-49`
**Problem**: `contextlib.suppress(curses.error)` eats *every* curses error, including negative coordinates, out-of-bounds writes, and null window references. These are programming bugs, not environmental conditions like narrow terminals.
**Plan**:
1. Change `_safe_addstr` to only suppress when the string is wider than the window (a known, expected condition), or when `x + len(s) > w`.
2. For all other `curses.error` cases, log a `WARNING` with `y, x, w, s[:20]`.
3. Alternatively, split into `_safe_addstr` (narrow-terminal safe) and `_debug_addstr` (no suppression, used in test builds).
4. **Result**: Visual layout bugs surface immediately during development, while narrow terminals remain graceful.

### 3.2 Fix `Player.stop()` potential orphan thread
**File**: `src/lxradio/player.py:89-106`
**Problem**: If `stop()` is called while the metadata thread is alive but `join(timeout=1)` times out, `_metadata_thread` is set to `None` anyway. The daemon thread continues running, potentially holding a reference to the old `Popen` stdout pipe.
**Plan**:
1. Set a `_stop_requested = threading.Event()` flag.
2. `_read_output` checks `_stop_requested.is_set()` inside the `for line in proc.stdout:` loop and breaks promptly.
3. `stop()` sets the event, then joins, then clears it.
4. **Result**: Threads terminate deterministically within milliseconds, not after the next stdout line arrives.

### 3.3 Cache negative DNS results briefly
**File**: `src/lxradio/radio_browser.py:65-85`
**Problem**: If `all.api.radio-browser.info` is unreachable, `_resolve_host()` repeats the failing `socket.getaddrinfo()` call every time. A transient DNS outage causes a multi-second stall on every API call.
**Plan**:
1. Cache the *failure* for a shorter TTL (e.g., 30 seconds) so repeated calls within an outage window immediately fall back to `_FALLBACK_HOSTS[0]`.
2. Distinguish "cached success" from "cached failure" in the cache state.
3. **Result**: Resilient to DNS outages without hammering the resolver.

---

## 4. Testability → A

### 4.1 Replace inline code-copy race guard test
**File**: `tests/test_app.py`
**Problem**: `test_maybe_load_more_double_lock_race_guard` contains a copy-pasted reproduction of `_maybe_load_more`’s logic. If the real method is refactored, the test tests stale code and gives false confidence.
**Plan**:
1. Refactor `_maybe_load_more` so the race window is injectable: extract a `_should_trigger_load(stations_count, offset, cursor, loading, has_more)` pure function that returns `bool` and the offset to load.
2. Test `_should_trigger_load` directly with synthetic inputs.
3. Test `_maybe_load_more` as an integration test by mocking `threading.Lock` with a fake lock that flips `_loading` on `__exit__`.
4. **Result**: No inline code duplication. The race guard is tested against the real method.

### 4.2 Add integration tests for the event loop
**Problem**: `_main()`'s `while True` loop is entirely untested. A regression in the `quit_` logic or the `_dirty` flag clearing would only be caught manually.
**Plan**:
1. Extract the loop body into a `_tick(key: int) -> bool` method that returns `True` for quit.
2. `_main` becomes a thin wrapper: `while not self._tick(stdscr.getch()): ...`
3. Test `_tick` with synthetic key inputs: assert `_search_mode` transitions, `_start_load` is called, `True` is returned for `q`, etc.
4. **Result**: The event dispatching logic has regression coverage without needing a real terminal.

---

## 5. Performance → A

### 5.1 Parallelise `search()` name + tag queries
**File**: `src/lxradio/radio_browser.py:138-154`
**Problem**: `search()` calls `search_by_name` and `search_by_tag` sequentially. Each is an 8-second-timeout network round-trip. The worst-case latency is ~16 seconds.
**Plan**:
1. Use `concurrent.futures.ThreadPoolExecutor(max_workers=2)` to fire both requests concurrently.
2. Gather results, dedupe, sort, slice.
3. Reuse a module-level executor to avoid thread creation overhead.
4. **Result**: Search latency drops to the slower of the two calls, not the sum.

### 5.2 Cache `_has_pactl()` result
**File**: `src/lxradio/player.py:20-21`
**Problem**: `shutil.which("pactl")` does filesystem `stat` calls on every `can_control_volume()` invocation, which happens on every redraw (~5 times/second).
**Plan**:
1. Cache the result in a module-level `_PACTL_AVAILABLE: bool | None = None`.
2. First call probes the filesystem; subsequent calls return the cached boolean.
3. Invalidate lazily (not needed for a CLI app lifecycle).
4. **Result**: Eliminates ~150 redundant filesystem syscalls per minute of use.

### 5.3 Move tag truncation from ingestion to display
**File**: `src/lxradio/radio_browser.py:34`
**Problem**: `Station.from_api()` truncates tags to 4 at parse time. If a station has 8 tags, downstream code (search, filtering, future tag cloud) never sees the other 4.
**Plan**:
1. Store all tags in `Station.tags`.
2. `tag_str` already truncates for display. Extend it to accept an optional `max_tags` parameter defaulting to 4.
3. Update `_draw_station_row` to use `s.tag_str` with the display limit.
4. **Result**: Full tag data available for logic; display truncation stays where it belongs.

---

## 6. Maintainability → A

### 6.1 Replace magic column constants with named layout
**File**: `src/lxradio/app.py:217-234`
**Problem**: `country_col = 36`, `tag_col = 42`, `w - tag_col - 14`, `w - len(quality) - 2` are scattered magic numbers. A 2-column change to the name width requires editing 4 separate expressions.
**Plan**:
1. Define a `StationRowLayout` dataclass or `NamedTuple` with `name_w`, `country_col`, `tag_col`, `tag_w`, `quality_col`.
2. Provide a `compute_layout(w: int) -> StationRowLayout` function.
3. `_draw_station_row` uses the layout object exclusively.
4. **Result**: One place to change the layout. The layout computation is independently testable.

### 6.2 Add public `shutdown()` to `RadioApp`
**File**: `src/lxradio/app.py`, `src/lxradio/__main__.py`
**Problem**: `__main__.py` reaches into `app._player.stop()` (private attribute access). This is a module boundary violation.
**Plan**:
1. Add `RadioApp.shutdown() -> None` that stops the player and clears any pending loaders.
2. Update `__main__.py` to call `app.shutdown()`.
3. **Result**: `RadioApp` encapsulates its own lifecycle. `__main__.py` only uses the public API.

### 6.3 Consolidate `_draw_station_row` early-return logic
**File**: `src/lxradio/app.py:221-222`
**Problem**: `if w < 60: return` is an abrupt early return in the middle of a 30-line method. It skips country, tags, and quality without making it obvious *why* 60 is the cutoff.
**Plan**:
1. Move the width check into `compute_layout()`: if `w < 60`, return a layout with `show_details = False`.
2. `_draw_station_row` becomes:
   ```python
   layout = compute_layout(w)
   if selected: ...
   draw_name(layout)
   if layout.show_details:
       draw_country(layout)
       draw_tags(layout)
       draw_quality(layout)
   ```
3. **Result**: The cutoff is a property of the layout, not a hidden guard clause.

---

## Coverage Targets

| Module | Current | Target | Gap |
|--------|---------|--------|-----|
| `app.py` | 90% | 98% | `_main` loop, complex draw paths |
| `player.py` | 99% | 100% | `_system_volume` Linux success path (CI on Linux) |
| `radio_browser.py` | 100% | 100% | — |
| `favorites.py` | 100% | 100% | — |
| **TOTAL** | **94%** | **98%+** | |

---

## Completion Criteria

- [x] `RadioApp` < 250 lines; `Renderer` extracted and tested.
- [x] `KeyDispatcher` implemented; keybindings are registration-driven.
- [x] `_load_batch` worker sets `_status_msg` inside the lock.
- [x] `_safe_addstr` distinguishes narrow-terminal suppression from bug logging.
- [x] `Player.stop()` uses `_stop_requested` event for deterministic thread shutdown.
- [x] DNS failure caching added to `_resolve_host()`.
- [x] `test_maybe_load_more_double_lock_race_guard` removed or rewritten against real code.
- [x] `_tick` extracted from `_main` and unit-tested.
- [x] `search()` uses `ThreadPoolExecutor` for parallel name/tag queries.
- [x] `_has_pactl()` caches its result.
- [x] Tag truncation moved from `from_api` to `tag_str`.
- [x] `StationRowLayout` replaces magic column numbers.
- [x] `RadioApp.shutdown()` added; `__main__.py` uses it.

---

*Target completion: next development cycle. Items are ordered by dependency — Renderer extraction should happen before KeyDispatcher, which should happen before `_tick` testing.*
