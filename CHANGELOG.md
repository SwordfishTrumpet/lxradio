# Changelog

All notable changes to lxradio will be documented in this file.

## [0.2.0] — 2026-08-18

### Added

- **Listening history** — every station played and its song metadata is logged to `~/.config/lxradio/history.jsonl` (capped at 1000 entries, JSONL format). `Tab` now cycles through Browse → Favourites → History view. History entries show a relative timestamp and can be replayed instantly without an API call. Player emits `on_history` events on playback start and metadata change.
- **Sleep-timer volume restoration** — the volume that was active when a sleep preset was set is restored automatically when the timer is cancelled, expires, is turned off, or a new station is played/stopped, so the fade never leaves the next session silent or quiet.

### Changed

- `Player.play()` now accepts a `Station` object instead of a raw URL string.
- `Player.is_playing()` is now process-based (`mpv` process alive = playing) instead of relying on a metadata heartbeat, so silent streams are no longer mistaken for stopped ones.
- Broad free-text searches now return a single page (infinite scroll is disabled for merged results, whose pagination was inconsistent).
- History keeps one entry per station session: a new song for a station you're already listening to replaces the previous entry instead of flooding the log.

### Fixed

- A malformed or unexpected API payload can no longer leave the app stuck in a perpetual "loading…" spinner; load errors are always surfaced as a friendly status.
- Stale background search results no longer pollute a newer search (generation guard).
- Searching from the Favourites or History view now correctly switches to Browse and shows the results.
- Failed playback and stopping with Space no longer leave a stale "now playing" bar on screen.
- DNS resolution errors are now recognized on Linux as well as macOS, producing the friendly "cannot resolve" message.
- Over-long header labels keep the app identity instead of showing only the trailing count.
- Background metadata/error callbacks now write app state under the documented lock, and the history cache is invalidated on new entries.
- `toggle_mute` behaves correctly at volume 0 (restores the last non-zero volume).
- `shutdown()` now cancels an active sleep timer.
- A minimum-terminal-size guard prevents layout errors on very small windows.

## [0.1.0] — 2025-05-25

### Added

- Initial release: terminal TUI radio player using curses + mpv
- Browse top-voted stations from radio-browser.info
- Parallel search (name, tag, country) with deduplication
- Paginated loading with background threads
- Favourites management with atomic JSON writes and corruption recovery
- App-scoped volume control via mpv IPC (with pactl fallback on Linux)
- Heartbeat detection for stale streams
- Click deduplication for API tracking
- Registration-driven keybindings with auto-generated footer

[0.2.0]: https://github.com/SwordfishTrumpet/lxradio/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/anomalyco/lxradio/releases/tag/v0.1.0
