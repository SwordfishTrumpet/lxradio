# Sleep Timer with Fade-Out — Design Spec

## Overview

Add a sleep timer that counts down and gradually fades out mpv volume before stopping playback. Controlled via a single key (`s`) that cycles through preset durations.

## UX

- **`s`** cycles: 15m → 30m → 60m → Custom → Off
- **`S`** (shift) cancels active timer
- Custom: a prompt asks for minutes, Enter confirms
- Header shows `Sleep: MM:SS` countdown when active
- During last 60s (fading), text turns yellow/bold
- Starting a new station cancels the timer
- Stopping playback manually (Space) cancels the timer
- Fade duration: hardcoded 60 seconds

## Architecture

### New: `src/lxradio/sleep_timer.py`

`SleepTimer` class with daemon thread, fade logic, and thread-safe state:
- `start(duration_sec)` — spawns countdown thread, cancels any existing
- `cancel()` — signals stop_event, joins thread
- `remaining_seconds()` → float — lock-protected, for renderer
- `is_active()` → bool
- `is_fading()` → bool
- `state` → "idle" | "running" | "fading" | "expired"
- Thread sleeps 1s ticks; last 60s steps volume down every 2s

### Modified files

| File | Changes |
|------|---------|
| `player.py` | Expose `volume` property (returns `_volume`, already exists as `get_volume()`) |
| `app.py` | Instantiate `SleepTimer`, wire callbacks, add timer methods |
| `renderer.py` | `DrawState` gains `sleep_remaining`, `sleep_state`. Header renders sleep countdown. |
| `key_dispatcher.py` | Register `s` (cycle) and `S` (cancel), with `when` predicate |

## State machine

```
IDLE ──start()──▶ RUNNING ──≤60s──▶ FADING ──0s──▶ EXPIRED → IDLE
  ▲                  │        ▲
  │   cancel()       │        │ cancel()
  └──────────────────┴────────┘
```

## Fade algorithm

- At fade start: read `player.volume` as baseline
- 30 steps over 60s (one every 2s)
- `step = baseline_volume / 30`, minimum step 1
- Each step: `player.set_volume(max(0, volume - step))`
- IPC failures during fade → silent catch, timer still expires

## Edge cases

- Timer expires while mpv stopped → harmless no-op
- `s` during fade → cancels current, starts new with fresh baseline
- Set timer < 60s → skip to FADING immediately, compress steps
- Rapid `s` presses → only final selection takes effect
- Zero volume at start → fade is no-op, timer still counts

## Testing

New `tests/test_sleep_timer.py`:
- `test_start_creates_thread_and_counts`
- `test_fade_reduces_volume`
- `test_cancel_stops_thread`
- `test_state_transitions`
- `test_short_timer_skips_to_fading`

Modify `tests/test_app.py`:
- `test_sleep_timer_cycles_presets`
- `test_sleep_timer_cancel`
- `test_new_station_cancels_timer`

Modify `tests/test_renderer.py`:
- `test_header_shows_sleep_countdown`
- `test_header_shows_fading_indicator`
