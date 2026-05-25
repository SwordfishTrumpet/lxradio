# Changelog

All notable changes to lxradio will be documented in this file.

## [Unreleased]

### Added

- **Listening history** — every station played and its song metadata is logged to `~/.config/lxradio/history.jsonl` (capped at 1000 entries, JSONL format). `Tab` now cycles through Browse → Favourites → History view. History entries show a relative timestamp and can be replayed instantly without an API call. Player emits `on_history` events on playback start and metadata change.

### Changed

- `Player.play()` now accepts a `Station` object instead of a raw URL string.

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

[Unreleased]: https://github.com/anomalyco/lxradio/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/anomalyco/lxradio/releases/tag/v0.1.0
