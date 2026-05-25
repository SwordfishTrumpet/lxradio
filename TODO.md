# TODO: Persistent Listening History with Song Timeline

## Overview
Add a third view (History) that logs every station played and the song metadata received, allowing users to browse their listening session, see timestamps, and jump back to previously played stations.

## Architecture

```
src/lxradio/
  history.py        — NEW: listening log manager (JSONL persistence)
  player.py         — MOD: emit history events alongside metadata
  app.py            — MOD: add HISTORY view, handlers, state
  renderer.py       — MOD: draw history entries in station list
  key_dispatcher.py — MOD: register 'h' keybinding for history view
  radio_browser.py  — NO CHANGE
  favorites.py      — NO CHANGE

tests/
  test_history.py   — NEW: atomic writes, corruption recovery, cap enforcement
  test_app.py     — MOD: history view switching, history-based playback
  test_renderer.py — MOD: history row rendering (or reuse station row)
```

---

## Phase 1: Core History Module

### 1.1 Create `src/lxradio/history.py`
**Goal:** Self-contained, testable history manager mirroring `favorites.py` patterns.

**Requirements:**
- Store entries as JSONL (`~/.config/lxradio/history.jsonl`) for append-only efficiency
- Each entry: `{timestamp, station_id, station_name, url, country, tags, codec, bitrate, votes, favicon, song_title}`
- Cap at **1000 entries** — on load, trim oldest if over limit
- Atomic writes: write to `.tmp`, `os.replace`
- Corruption handling: if last line is malformed, skip it and log warning (JSONL means one bad line doesn't destroy the file)
- Public API:
  - `add(station: Station, song_title: str = "") -> None`
  - `all() -> list[HistoryEntry]` — newest first
  - `get(station_id: str) -> HistoryEntry | None` — most recent for that station
  - `clear() -> None`

**Design decisions:**
- Use `@dataclass(frozen=True)` for `HistoryEntry` (immutable, hashable)
- JSONL instead of JSON array: append is O(1) vs. O(n) rewrite; trim on load is acceptable since 1000 lines is trivial
- Follow `favorites.py` config directory pattern: `_CONFIG_DIR / "history.jsonl"`

### 1.2 Tests for `history.py`
**File:** `tests/test_history.py`

**Cases:**
- [x] `test_add_creates_file` — first entry writes to tmp then replaces
- [x] `test_all_returns_newest_first` — append 3 entries, verify order
- [x] `test_cap_trims_oldest` — add 1002 entries, verify only 1000 remain, oldest evicted
- [x] `test_load_skips_malformed_last_line` — write valid + malformed line, verify load succeeds
- [x] `test_get_returns_most_recent` — add same station twice with different songs, verify most recent returned
- [x] `test_clear_empties_file` — add entries, clear, verify `all()` returns `[]`
- [x] `test_corruption_backup` — if entire file is invalid JSON, backup to `.bak` and start fresh (same pattern as favorites)
- [x] `test_thread_safety` — spawn 10 threads adding simultaneously, verify all entries present (no data loss)

**Monkeypatch targets:** `_CONFIG_DIR`, `_HISTORY_FILE` to `tmp_path`

---

## Phase 2: Player Integration

### 2.1 Modify `src/lxradio/player.py`
**Goal:** Emit a history event when a station starts playing and when song metadata changes.

**Changes:**
- Add `on_history: Callable[[str, str], None] | None` callback parameter to `__init__`
  - Signature: `(station_id: str, song_title: str) -> None`
  - Alternative: pass full `Station` object — but `Player` currently only receives `url`. We need to change `play()` signature.

**Decision needed:** Should `play()` accept a `Station` instead of just `url`?
- **Option A:** `play(station: Station) -> bool` — breaks existing interface, requires updating `app.py` call sites
- **Option B:** Keep `play(url: str)` but add `play_station(station: Station) -> bool` — cleaner separation
- **Option C:** `play(url: str, station_id: str = "", station_name: str = "")` — backward compatible

**Recommended: Option A** — `play(station: Station)` because the Player is inherently station-aware (metadata, history). This is a small breaking change in a small codebase.

**Implementation:**
- Change `play(self, url: str)` → `play(self, station: Station)`
- Store `_current_station: Station | None = None`
- When metadata arrives (`_read_output`), call:
  ```python
  if self._on_history and self._current_station:
      self._on_history(self._current_station.id, title)
  ```
- Also call `on_history` when `play()` succeeds (with empty `song_title` to log "started playing")

### 2.2 Update `src/lxradio/app.py` — Player construction
**Changes:**
- `self._player = Player(on_metadata=..., on_error=..., on_history=self._on_history)`

### 2.3 Update `tests/test_player.py`
**Cases:**
- [x] `test_play_emits_history_on_start` — mock `on_history`, call `play(station)`, verify called with `(station.id, "")`
- [x] `test_metadata_emits_history_with_title` — mock `on_history`, simulate metadata line, verify called with `(station.id, "Song Title")`
- [x] `test_play_station_sets_current_station` — verify `Player._current_station` is set after play

---

## Phase 3: App Layer — New View & Navigation

### 3.1 Extend `View` enum in `app.py`
```python
class View(Enum):
    BROWSE = auto()
    FAVORITES = auto()
    HISTORY = auto()
```

### 3.2 Add history state to `RadioApp.__init__`
```python
self._history = History()
```

### 3.3 Add `_on_history` callback
```python
def _on_history(self, station_id: str, song_title: str) -> None:
    # Find station in current list or history
    station = self._find_station(station_id)
    if station:
        self._history.add(station, song_title)
```

**Question:** What if the station isn't in `_stations` anymore (e.g., scrolled away)?
- Store a `_station_cache: dict[str, Station]` that retains every station ever seen in the session. History entries include full station data, so the cache is only needed for the current session — `history.py` already stores full metadata.

### 3.4 Add history view switching
```python
def _switch_view_history(self) -> None:
    self._switch_view(View.HISTORY)
```

### 3.5 Modify `_current_stations()` to return history entries
```python
def _current_stations(self) -> list[Station]:
    if self._view == View.FAVORITES:
        return self._favorites.all()
    if self._view == View.HISTORY:
        return [entry.to_station() for entry in self._history.all()]
    with self._lock:
        return list(self._stations)
```

**Design note:** `HistoryEntry.to_station()` reconstructs a `Station` dataclass so the renderer can treat history rows the same as station rows. This keeps the renderer changes minimal.

### 3.6 Modify `_play_selected()` to handle history view
When playing from history, the entry already has full station data — no API call needed. This is actually a feature: instant replay from history.

### 3.7 Modify `_enter()` for history view
When `Enter` is pressed in history view:
- If the selected entry's station is already playing → toggle mute (same behavior)
- Else → play that station directly (no API call needed, full metadata in history entry)

### 3.8 Add history-aware keybinding in `key_dispatcher.py`
```python
d.register(KeyBinding((ord("h"), ord("H")), lambda app: app._cycle_view(), "Tab view"))
```

Wait — current `Tab` cycles between Browse and Favourites. With 3 views, we need a cleaner cycle.

**Decision:** Replace `_switch_view()` with `_cycle_view()` that rotates: BROWSE → FAVORITES → HISTORY → BROWSE.

Or: Keep `Tab` for Browse↔Favourites, and `h`/`H` for History. This is more predictable for existing users.

**Recommended: Cycle on Tab** — simpler mental model: "Tab cycles through all views."

Update `key_dispatcher.py`:
```python
def _cycle_view(app: RadioApp) -> None:
    current = app._view
    if current == View.BROWSE:
        app._switch_view(View.FAVORITES)
    elif current == View.FAVORITES:
        app._switch_view(View.HISTORY)
    else:
        app._switch_view(View.BROWSE)

d.register(KeyBinding((ord("\t"),), _cycle_view, "Tab view"))
```

### 3.9 Tests for `app.py` changes
**File:** `tests/test_app.py`

**Cases:**
- [x] `test_tab_cycles_through_views` — BROWSE → FAVORITES → HISTORY → BROWSE
- [x] `test_history_view_shows_history_entries` — add history entry, switch to HISTORY, verify in draw state
- [x] `test_enter_in_history_plays_station` — select history entry, press Enter, verify `Player.play()` called with correct Station
- [x] `test_history_callback_adds_entry` — simulate `on_history`, verify `History.all()` contains entry
- [x] `test_history_view_empty_message` — no history, switch to HISTORY, verify "No listening history yet." message

---

## Phase 4: Renderer Changes

### 4.1 History entry display
History entries are shown in the same station list area but with an extra timestamp column.

**Decision:** How to display history?
- Option A: Reuse station row exactly (name, country, tags, quality) — simple but loses the "history" context (when was it played?)
- Option B: Add a timestamp column, drop some station detail
- Option C: Show timestamp + station name + song title (compact)

**Recommended: Option C for narrow terminals, Option B for wide**

**Layout for history rows:**
```
▶ ★ Station Name    2m ago    Song Title — Quality
```

**Implementation in `renderer.py`:**
- `DrawState` gets `is_history_view: bool` field
- `_draw_station_row()` checks `is_history_view` and renders timestamp + song title instead of country/tags
- Or: keep `_draw_station_row()` unchanged for history (shows station metadata), and add a subtle timestamp in dim text after the name

**Simpler approach:** Keep station row identical, prepend a compact timestamp in the play symbol column:
```
2m ★ Station Name    Country    Tags    Quality
```

This requires minimal renderer changes. The "play symbol" becomes a "time ago" string when in history view.

### 4.2 Add history header label
```python
view_label="HISTORY" if self._view == View.HISTORY else ...
```

### 4.3 Tests for renderer
**Cases:**
- [x] `test_history_row_shows_timestamp` — verify "2m" or "1h" appears in history row
- [x] `test_history_header_label` — verify header says "HISTORY"

---

## Phase 5: KeyDispatcher & Footer

### 5.1 Update footer text
The `Tab view` description should still work — it already dynamically generates from the registry.

### 5.2 Consider adding `H` shortcut
Add `d.register(KeyBinding((ord("h"), ord("H")), _cycle_view, ""))` as an alternative to Tab? No — keep it simple. Tab is sufficient.

### 5.3 Add `c` for clear history?
Could be useful but out of scope for MVP. Add if user requests.

---

## Phase 6: Testing & Quality

### 6.1 Run full test suite
```bash
uv run pytest tests/ -v
```

**Expected:** All existing tests pass + new tests pass.

### 6.2 Run linting
```bash
uv run ruff check src/ tests/
```

**Expected:** No new warnings.

### 6.3 Run type checking
```bash
uv run mypy src/
```

**Expected:** No type errors in new code.

### 6.4 Manual test checklist
- [ ] Start app, play a station, verify `~/.config/lxradio/history.jsonl` created
- [ ] Switch to History view with `Tab`, see the entry
- [ ] Play another station, switch back to History, see both entries newest-first
- [ ] Press Enter on a history entry, station plays immediately (no API spinner)
- [ ] Close and reopen app, History view still shows previous entries
- [ ] Let 1001 stations play (or script it), verify oldest entry is evicted

---

## Phase 7: Documentation

### 7.1 Update `README.md`
- Add `Tab` cycles through BROWSE → FAVOURITES → HISTORY
- Add `History view` to Features list
- Mention `~/.config/lxradio/history.jsonl` for power users

### 7.2 Update `AGENTS.md` (if needed)
- Add `history.py` to Architecture tree
- Document `History` class under "Persistent data" section (atomic writes, JSONL, cap)

---

## Open Questions / Decisions

1. **Station cache for history entries:** Should `RadioApp` keep a `_station_cache: dict[str, Station]` of every station loaded in the session, so `HistoryEntry` always has full metadata even if the station isn't in the current list?
    - **Answer: Yes** — simple `dict`, populated in `_load_batch()` and `_play_selected()`.

2. **Timestamp format:** Human-readable relative ("2m ago", "1h ago") or absolute ("14:32")?
    - **Answer: Relative** for terminal compactness. Use simple helper: `<60s` → "now", `<60min` → "{m}m", `<24h` → "{h}h", else "{d}d".

3. **Song title in history row:** Should the currently playing song be shown in the history list, or just the station name?
    - **Answer: Show both** — station name + most recent song title (from history entry). If no song title, show "—".

4. **History entry deduplication:** If you replay the same station 5 times, do you see 5 entries or 1 with updated timestamp?
    - **Answer: 5 entries** — history is a log, not a favourites list. Each play is a distinct event.

5. **Should favourites be shown in history view?**
    - **Answer: No** — history is a separate concept. The star indicator still works if the history station is also a favourite.

---

## Implementation Order

1. **Create `history.py` + tests** — independent, no other changes needed
2. **Update `player.py` + tests** — add `Station` parameter, history callback
3. **Update `app.py` + tests** — integrate History, add view, handle playback from history
4. **Update `renderer.py` + tests** — history row rendering with timestamp
5. **Update `key_dispatcher.py`** — cycle through 3 views
6. **Run full verification** — pytest, ruff, mypy, manual test
7. **Update docs** — README, AGENTS.md

---

## Definition of Done

- [x] `history.py` exists, tested, with 1000-entry cap and atomic JSONL writes
- [x] `Player.play()` accepts `Station` and emits history events
- [x] `RadioApp` has `HISTORY` view, accessible via `Tab`
- [x] History entries show relative timestamp in renderer
- [x] Pressing Enter on history entry plays station without API call
- [x] All tests pass (pytest)
- [x] Lint passes (ruff)
- [x] Type check passes (mypy)
- [x] README and AGENTS.md updated
- [ ] Manual test completed
