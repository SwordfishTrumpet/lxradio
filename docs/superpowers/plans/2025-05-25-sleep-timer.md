# Sleep Timer with Fade-Out — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sleep timer that counts down and gradually fades out mpv volume before stopping playback, controlled via a single `s` key.

**Architecture:** New `SleepTimer` class in `src/lxradio/sleep_timer.py` manages a daemon thread that counts down in 1s ticks, switches to fading state for the last 60s (stepping volume down every 2s via the Player), and calls an `on_expire` callback at zero. `RadioApp` wires it in, `Renderer` shows countdown + fade state in header, `KeyDispatcher` registers `s`/`S`.

**Tech Stack:** Python ≥ 3.10, threading, curses

---

### Task 1: Create SleepTimer module

**Files:**
- Create: `src/lxradio/sleep_timer.py`
- Create: `tests/test_sleep_timer.py`

- [ ] **Step 1: Create the SleepTimer class**

Write `src/lxradio/sleep_timer.py`:

```python
import threading
from collections.abc import Callable


class SleepTimer:
    """Countdown timer that fades out mpv volume before expiry."""

    PRESETS = [15 * 60, 30 * 60, 60 * 60]
    FADE_DURATION = 60
    FADE_INTERVAL = 2

    def __init__(
        self,
        get_volume: Callable[[], int],
        set_volume: Callable[[int], None],
        on_expire: Callable[[], None],
    ) -> None:
        self._get_volume = get_volume
        self._set_volume = set_volume
        self._on_expire = on_expire
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._remaining: float = 0.0
        self._state: str = "idle"
        self._preset_index: int = -1

    def start(self, duration_sec: int) -> None:
        self.cancel()
        with self._lock:
            self._remaining = float(duration_sec)
            self._state = "running"
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None
        with self._lock:
            self._remaining = 0.0
            self._state = "idle"

    def remaining_seconds(self) -> float:
        with self._lock:
            return self._remaining

    def is_active(self) -> bool:
        with self._lock:
            return self._state in ("running", "fading")

    def is_fading(self) -> bool:
        with self._lock:
            return self._state == "fading"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def preset_index(self) -> int:
        return self._preset_index

    @preset_index.setter
    def preset_index(self, value: int) -> None:
        self._preset_index = value

    def cycle_preset(self) -> tuple[str, int] | None:
        n = len(self.PRESETS)
        self._preset_index = (self._preset_index + 1) % (n + 1)
        if self._preset_index >= n:
            return None
        duration = self.PRESETS[self._preset_index]
        return f"{duration // 60}m", duration

    def _run(self) -> None:
        fade_start_volume: int | None = None
        fade_start_remaining: float = 0.0
        last_step: int = 0

        while True:
            if self._stop_event.wait(timeout=1):
                return

            with self._lock:
                self._remaining -= 1
                if self._remaining <= self.FADE_DURATION and self._state == "running":
                    self._state = "fading"
                    fade_start_remaining = self._remaining
                    last_step = 0
                remaining = self._remaining
                state = self._state

            if state == "fading":
                if fade_start_volume is None:
                    fade_start_volume = self._get_volume()
                fade_elapsed = fade_start_remaining - remaining
                steps_so_far = int(fade_elapsed // self.FADE_INTERVAL)
                if steps_so_far > last_step:
                    last_step = steps_so_far
                    total_steps = max(fade_start_remaining / self.FADE_INTERVAL, 1)
                    progress = min(steps_so_far / total_steps, 1.0)
                    target = max(0, int(fade_start_volume * (1 - progress)))
                    try:
                        self._set_volume(target)
                    except OSError:
                        pass

            if remaining <= 0:
                with self._lock:
                    self._state = "expired"
                    self._remaining = 0.0
                self._on_expire()
                with self._lock:
                    self._state = "idle"
                return
```

- [ ] **Step 2: Write the test file**

Write `tests/test_sleep_timer.py`:

```python
import threading
import time

import pytest

from lxradio.sleep_timer import SleepTimer


class FakeVolume:
    def __init__(self, initial: int = 80) -> None:
        self._volume = initial
        self.calls: list[int] = []

    def get(self) -> int:
        return self._volume

    def set(self, v: int) -> None:
        self._volume = v
        self.calls.append(v)


@pytest.fixture
def vol() -> FakeVolume:
    return FakeVolume()


@pytest.fixture
def expired() -> list[bool]:
    return [False]


def make_timer(vol: FakeVolume, expired: list[bool]) -> SleepTimer:
    def on_expire() -> None:
        expired[0] = True

    return SleepTimer(get_volume=vol.get, set_volume=vol.set, on_expire=on_expire)


def test_start_creates_thread_and_counts(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    assert not timer.is_active()
    assert timer.remaining_seconds() == 0.0

    timer.start(5)
    assert timer.is_active()
    assert timer.state == "running"

    time.sleep(2.5)
    assert timer.remaining_seconds() <= 3
    assert timer.remaining_seconds() > 0
    assert timer.is_active()

    timer.cancel()


def test_cancel_stops_thread(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(30)
    assert timer.is_active()

    timer.cancel()
    assert not timer.is_active()
    assert timer.remaining_seconds() == 0.0
    assert timer.state == "idle"
    assert not expired[0]


def test_state_transitions(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    assert timer.state == "idle"

    timer.start(90)
    assert timer.state == "running"
    assert not timer.is_fading()

    timer.cancel()
    assert timer.state == "idle"


def test_fade_reduces_volume(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(3)
    time.sleep(0.3)
    assert timer.state == "fading"

    time.sleep(4)
    assert timer.state == "idle"
    assert expired[0]
    assert len(vol.calls) > 0
    assert vol.calls[0] < vol.get() or vol.calls[0] == 0
    assert vol.calls[-1] == 0


def test_short_timer_enters_fading_immediately(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(2)
    time.sleep(0.3)
    assert timer.state == "fading"

    timer.cancel()


def test_cycle_preset(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)

    result = timer.cycle_preset()
    assert result == ("15m", 900)

    result = timer.cycle_preset()
    assert result == ("30m", 1800)

    result = timer.cycle_preset()
    assert result == ("60m", 3600)

    result = timer.cycle_preset()
    assert result is None

    result = timer.cycle_preset()
    assert result == ("15m", 900)


def test_start_cancels_existing(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(30)
    time.sleep(0.1)
    timer.start(15)
    time.sleep(0.1)

    assert timer.is_active()
    assert timer.remaining_seconds() <= 15

    timer.cancel()


def test_expire_calls_callback(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(2)
    assert not expired[0]

    time.sleep(3)
    assert expired[0]
    assert timer.state == "idle"
    assert timer.remaining_seconds() == 0.0


def test_thread_safety_race(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)

    def toggle() -> None:
        for _ in range(100):
            timer.start(1)
            time.sleep(0.01)
            timer.cancel()

    threads = [threading.Thread(target=toggle) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    timer.cancel()
    assert not expired[0]
```

- [ ] **Step 3: Run the new tests to verify they pass**

```bash
uv run pytest tests/test_sleep_timer.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/lxradio/sleep_timer.py tests/test_sleep_timer.py
git commit -m "feat: add SleepTimer module with fade-out and presets"
```

---

### Task 2: Integrate SleepTimer into RadioApp

**Files:**
- Modify: `src/lxradio/app.py`

- [ ] **Step 1: Add SleepTimer import and instance in RadioApp.__init__**

In `src/lxradio/app.py`, add the import at the top (line 9 area):

```python
from .sleep_timer import SleepTimer
```

In `RadioApp.__init__`, add after the `self._player = Player(...)` line:

```python
self._sleep_timer = SleepTimer(
    get_volume=lambda: self._player.get_volume(),
    set_volume=lambda v: self._player.set_volume(v),
    on_expire=self._on_sleep_expire,
)
```

- [ ] **Step 2: Add sleep timer methods to RadioApp**

Add these methods to `RadioApp` (after `_toggle_mute` at line 161):

```python
def _on_sleep_expire(self) -> None:
    self._player.stop()
    self._song_title = ""
    self._status_msg = "Sleep timer finished"
    self._dirty = True

def _cycle_sleep_timer(self) -> None:
    result = self._sleep_timer.cycle_preset()
    if result is None:
        self._sleep_timer.cancel()
        self._status_msg = "Sleep timer off"
    else:
        label, duration = result
        self._sleep_timer.start(duration)
        self._status_msg = f"Sleep timer: {label}"
    self._dirty = True

def _cancel_sleep_timer(self) -> None:
    if self._sleep_timer.is_active():
        self._sleep_timer.cancel()
        self._status_msg = "Sleep timer cancelled"
        self._dirty = True
```

- [ ] **Step 3: Cancel sleep timer when starting a new station**

In `_play_selected` (around line 209), add before `self._song_title, self._status_msg = ...`:

```python
self._sleep_timer.cancel()
```

- [ ] **Step 4: Cancel sleep timer when stopping playback**

In `_space` (around line 164), add when stopping:

```python
def _space(self) -> None:
    stations = self._current_stations()
    if self._player.is_playing():
        self._player.stop()
        self._sleep_timer.cancel()
        self._status_msg = "Stopped"
    elif stations:
        self._play_selected()
    else:
        self._status_msg = "No station selected"
```

- [ ] **Step 5: Pass sleep timer state to DrawState**

In `_build_draw_state` (around line 95), add to the `DrawState(...)` constructor:

```python
sleep_remaining=self._sleep_timer.remaining_seconds(),
sleep_fading=self._sleep_timer.is_fading(),
```

- [ ] **Step 6: Add sleep timer keybinding**

In `add method to RadioApp._cycle_sleep_timer` — this is wired in Task 3 via key_dispatcher changes.

No changes needed here; keybinding is handled in Task 3.

- [ ] **Step 7: Add tests for sleep timer integration in app**

In `tests/test_app.py`, add these test methods to `TestRadioAppLogic` class (before the last test):

```python
def test_cycle_sleep_timer_sets_15m(self, app):
    app._cycle_sleep_timer()
    assert app._sleep_timer.is_active()
    remaining = app._sleep_timer.remaining_seconds()
    assert remaining <= 900
    assert remaining > 0
    app._sleep_timer.cancel()

def test_cycle_sleep_timer_cancels_on_off(self, app):
    app._cycle_sleep_timer()
    app._cycle_sleep_timer()
    app._cycle_sleep_timer()
    app._cycle_sleep_timer()
    assert not app._sleep_timer.is_active()
    assert app._sleep_timer.state == "idle"

def test_cancel_sleep_timer(self, app):
    app._cycle_sleep_timer()
    assert app._sleep_timer.is_active()
    app._cancel_sleep_timer()
    assert not app._sleep_timer.is_active()

def test_new_station_cancels_timer(self, app):
    s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
    app._stations = [s]
    app._cursor = 0
    app._view = View.BROWSE
    app._cycle_sleep_timer()
    assert app._sleep_timer.is_active()
    app._play_selected()
    assert not app._sleep_timer.is_active()

def test_space_stops_and_cancels_timer(self, app):
    app._player.is_playing.return_value = True
    app._cycle_sleep_timer()
    assert app._sleep_timer.is_active()
    app._space()
    assert not app._sleep_timer.is_active()
```

Wait — need to ensure the mock setup works with the existing fixture. The fixture already mocks `_player` as a `unittest.mock.MagicMock`. Let me check.

Actually, looking at the existing fixture in test_app.py, the `_player` is already a `MagicMock` with `can_control_volume` returning True and other attributes. So `is_playing` and `play` are mock methods. Let me adjust:

```python
def test_new_station_cancels_timer(self, app: RadioApp) -> None:
    app._cycle_sleep_timer()
    assert app._sleep_timer.is_active()
    app._play_selected()
    assert not app._sleep_timer.is_active()

def test_space_stops_and_cancels_timer(self, app: RadioApp) -> None:
    app._player.is_playing.return_value = True
    app._cycle_sleep_timer()
    assert app._sleep_timer.is_active()
    app._space()
    assert not app._sleep_timer.is_active()
```

- [ ] **Step 8: Run app tests**

```bash
uv run pytest tests/test_app.py -v -k "sleep"
```

Expected: new tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/lxradio/app.py tests/test_app.py
git commit -m "feat: integrate SleepTimer into RadioApp with cancel on play/stop"
```

---

### Task 3: Update KeyDispatcher for sleep timer keybindings

**Files:**
- Modify: `src/lxradio/key_dispatcher.py`

- [ ] **Step 1: Register `s` and `S` keybindings**

In `make_default_dispatcher()` in `src/lxradio/key_dispatcher.py`, add after the `m` mute binding (line 74):

```python
d.register(KeyBinding((ord("s"),), lambda app: app._cycle_sleep_timer(), "s sleep", when=lambda app: app._player.can_control_volume()))
d.register(KeyBinding((ord("S"),), lambda app: app._cancel_sleep_timer(), "", when=lambda app: app._player.can_control_volume()))
```

- [ ] **Step 2: Verify key dispatch in existing tests**

The existing `TestRadioAppLogic` tests for various keys should still pass. No `s` key test exists yet, but the `_cycle_sleep_timer` test from Task 2 covers the handler logic. The dispatch wiring is implicitly tested since `make_default_dispatcher()` is used in the fixture.

No additional test needed here; dispatch is tested indirectly through `_handle_nav_key`.

- [ ] **Step 3: Run all tests to verify nothing broke**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add src/lxradio/key_dispatcher.py
git commit -m "feat: register s/S keybindings for sleep timer"
```

---

### Task 4: Update Renderer for sleep timer display

Sleep timer is shown in the now-playing bar (not header), alongside the station name and volume.

**Files:**
- Modify: `src/lxradio/renderer.py`
- Modify: `tests/test_renderer.py`

- [ ] **Step 1: Add sleep timer fields to DrawState**

In the `DrawState` dataclass, add these fields after `history_timestamps` (line 118):

```python
sleep_remaining: float = 0.0
sleep_fading: bool = False
```

- [ ] **Step 2: Show sleep timer in _draw_now_playing when playing**

In `_draw_now_playing` (around line 279), modify the playing section. Find where `left` is built and insert the sleep timer between the title and the volume:

```python
def _draw_now_playing(self, state: DrawState, h: int, w: int) -> None:
    scr = self._scr
    y = h - 3

    _safe_addstr(scr, y, 0, "─" * w, _dim())

    if state.now_playing:
        name = state.now_playing.name
        title = state.song_title
        vol = state.player_volume

        sleep_timer = ""
        if state.sleep_remaining > 0:
            mins = int(state.sleep_remaining // 60)
            secs = int(state.sleep_remaining % 60)
            sleep_timer = f"  Sleep: {mins:02d}:{secs:02d}"

        left = f"  ▶  {name}"
        if title:
            left += f"  —  {title}"
        left += sleep_timer
        vol_w = 16 if state.player_can_control_volume else 0
        left = _trunc(left, w - vol_w)

        _safe_addstr(scr, y + 1, 0, left, curses.color_pair(C.TITLE_SONG) | curses.A_BOLD)

        if state.sleep_remaining > 0:
            sleep_w = len(sleep_timer)
            sleep_x = max(0, w - vol_w - sleep_w)
            sleep_attr = curses.color_pair(C.TITLE_SONG) | curses.A_BOLD
            if state.sleep_fading:
                sleep_attr = curses.color_pair(C.TITLE_SONG) | curses.A_BOLD  # bold during fade
            _safe_addstr(scr, y + 1, sleep_x, sleep_timer, sleep_attr)

        if state.player_can_control_volume:
            vol_str = (
                "vol  MUTED   "
                if state.player_is_muted
                else f"vol {_vol_bar(vol)} {vol:3d}%  "
            )
            _safe_addstr(scr, y + 1, max(0, w - len(vol_str)), vol_str, _dim())
    else:
        idle = "  ◉  Not playing"
        if state.status_msg:
            idle += f"  —  {state.status_msg}"
        if state.sleep_remaining > 0:
            mins = int(state.sleep_remaining // 60)
            secs = int(state.sleep_remaining % 60)
            idle += f"  Sleep: {mins:02d}:{secs:02d}"
        _safe_addstr(scr, y + 1, 0, _trunc(idle, w), _dim())
```

Wait — this approach has a problem. The sleep timer text is already included in `left` via `left += sleep_timer`, and then it gets truncated with `_trunc(left, w - vol_w)`. If the title is long, the sleep timer might get truncated away. The second `_safe_addstr` draws it at a calculated position, but it's stale if `sleep_timer` was truncated from `left`.

Better approach: draw the sleep timer in `left` and use a visual separator. Don't draw it separately:

```python
def _draw_now_playing(self, state: DrawState, h: int, w: int) -> None:
    scr = self._scr
    y = h - 3

    _safe_addstr(scr, y, 0, "─" * w, _dim())

    if state.now_playing:
        name = state.now_playing.name
        title = state.song_title
        vol = state.player_volume

        sleep_timer = ""
        sleep_w = 0
        if state.sleep_remaining > 0:
            mins = int(state.sleep_remaining // 60)
            secs = int(state.sleep_remaining % 60)
            sleep_timer = f"  Sleep: {mins:02d}:{secs:02d}"
            sleep_w = len(sleep_timer)

        left = f"  ▶  {name}"
        if title:
            left += f"  —  {title}"
        vol_w = 16 if state.player_can_control_volume else 0
        avail = w - vol_w - sleep_w
        left = _trunc(left, avail) + sleep_timer

        _safe_addstr(scr, y + 1, 0, left, curses.color_pair(C.TITLE_SONG) | curses.A_BOLD)

        if state.player_can_control_volume:
            vol_str = (
                "vol  MUTED   "
                if state.player_is_muted
                else f"vol {_vol_bar(vol)} {vol:3d}%  "
            )
            _safe_addstr(scr, y + 1, max(0, w - len(vol_str)), vol_str, _dim())
    else:
        idle = "  ◉  Not playing"
        if state.status_msg:
            idle += f"  —  {state.status_msg}"
        if state.sleep_remaining > 0:
            mins = int(state.sleep_remaining // 60)
            secs = int(state.sleep_remaining % 60)
            idle += f"  Sleep: {mins:02d}:{secs:02d}"
        _safe_addstr(scr, y + 1, 0, _trunc(idle, w), _dim())
```

This is cleaner — the sleep timer is appended after truncation, so it always shows. The truncation of `left` reserves space for the sleep timer via `avail = w - vol_w - sleep_w`.

- [ ] **Step 3: Run existing renderer tests first to ensure no breakage**

```bash
uv run pytest tests/test_renderer.py -v
```

Expected: all 17 existing tests still pass. New `sleep_remaining=0.0` and `sleep_fading=False` defaults mean empty sleep timer is invisible.

- [ ] **Step 4: Add renderer tests for sleep timer**

Add to `TestRenderer` in `tests/test_renderer.py`:

```python
def test_now_playing_shows_sleep_timer(self, renderer):
    s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
    state = self._make_state(
        now_playing=s, song_title="Song", player_can_control_volume=True,
        sleep_remaining=930.0, sleep_fading=False,
    )
    renderer._draw_now_playing(state, 24, 80)
    calls = renderer._scr.addstr.call_args_list
    texts = [c[0][2] for c in calls]
    assert any("Sleep: 15:30" in t for t in texts)

def test_now_playing_shows_sleep_timer_when_not_playing(self, renderer):
    state = self._make_state(
        sleep_remaining=60.0, sleep_fading=True, status_msg=""
    )
    renderer._draw_now_playing(state, 24, 80)
    calls = renderer._scr.addstr.call_args_list
    texts = [c[0][2] for c in calls]
    assert any("Sleep: 01:00" in t for t in texts)

def test_now_playing_no_sleep_when_inactive(self, renderer):
    s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
    state = self._make_state(now_playing=s, song_title="Song")
    renderer._draw_now_playing(state, 24, 80)
    calls = renderer._scr.addstr.call_args_list
    texts = [c[0][2] for c in calls]
    assert not any("Sleep:" in t for t in texts)
```

- [ ] **Step 5: Run renderer tests**

```bash
uv run pytest tests/test_renderer.py -v -k "sleep or now_playing"
```

Expected: new tests pass, existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lxradio/renderer.py tests/test_renderer.py
git commit -m "feat: render sleep timer countdown in now-playing bar"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Run linting**

```bash
uv run ruff check src/ tests/
```

Expected: no warnings.

- [ ] **Step 3: Run type checking**

```bash
uv run mypy src/
```

Expected: no type errors.

- [ ] **Step 4: Commit if any fixes were made**

```bash
git add -u
git commit -m "chore: fix lint and type issues from sleep timer"
```

---

### Task 6: Update documentation

- [ ] **Step 1: Update README.md keybindings table**

Find the keybindings table in `README.md` and add a row:

```markdown
| `s` | Set sleep timer (15m → 30m → 60m → Off) |
| `S` | Cancel sleep timer |
```

- [ ] **Step 2: Update AGENTS.md architecture tree**

In `AGENTS.md`, add to the architecture section:

```
  sleep_timer.py     — countdown timer with fade-out (SleepTimer)
```

And add a new section under "Key architectural rules":

```markdown
### Sleep timer
- Daemon thread counts down in 1s ticks; thread-safe `_remaining` and `_state` protected by `_lock`.
- Last 60s: fades mpv volume proportionally every 2s via the Player's `set_volume`.
- Cancelled automatically when starting a new station or stopping playback.
- `SleepTimer` accepts callables for volume get/set, keeping it decoupled from `Player`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: document sleep timer feature"
```
