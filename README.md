# lxradio

A minimal, fast terminal radio player. Browse and search thousands of internet radio stations from [radio-browser.info](https://www.radio-browser.info/), manage favourites, and play streams via `mpv`.

## Requirements

- Python ≥ 3.10
- [mpv](https://mpv.io/) (must be available in `PATH`)

## Installation

```bash
pip install lxradio
```

## Usage

```bash
lxradio
```

## Keybindings

| Key | Action |
|-----|--------|
| `↑` / `↓` or `j` / `k` | Navigate station list |
| `Enter` | Play selected station |
| `Space` | Stop playback |
| `f` | Toggle favourite (browse & favourites view) |
| `Tab` | Switch between browse / favourites view |
| `/` | Search by name (prefix with `tag:` for tag search) |
| `+` / `=` | Volume up |
| `-` | Volume down |
| `q` | Quit |

## Search

- Type a name to search stations by name.
- Prefix with `tag:` to search by a single tag, e.g. `tag:jazz`.
- Use commas for multi-tag search, e.g. `tag:rock,classic`.

## Features

- **Thread-safe station loading** with fallback API hosts and DNS caching for fast browsing.
- **Parallel search** — free-text search queries the `name` and `tag` endpoints concurrently via `ThreadPoolExecutor`, cutting worst-case latency from ~16s to ~8s.
- **Paginated search** — free-text and tag searches load additional results as you scroll.
- **Atomic favourites** writes with automatic backup on corruption.
- **App-scoped volume** via mpv (no global system volume changes).
- **Graceful shutdown** on `SIGINT` / `SIGTERM` — mpv child processes are cleaned up.
- **Heartbeat detection** — stale streams are detected automatically.
- **Click deduplication** — rapid Enter presses on the same station are debounced to avoid duplicate API click-tracking requests.
- **Full tag data** — all station tags are retained internally; only display is truncated, enabling future tag filtering or cloud features.
- **Registration-driven keybindings** — adding a new shortcut is a single line of registration; footer help text is generated automatically.

## Known limitations

- **Linux volume**: On Linux, mpv IPC is attempted first for volume control; if the IPC socket is unavailable, `pactl` is used as a fallback. This means volume changes may still affect the global PulseAudio sink when mpv is not running or the socket is missing.
- **Multi-instance support**: The IPC socket path now includes the process ID (`/tmp/lxradio-mpv-{pid}.sock`), so multiple instances can run simultaneously without interfering with each other.
- **Empty search**: Submitting an empty search query does not reset the station list to top stations; the previously displayed results remain.
- **Merged search pagination**: Free-text search merges results from the `name` and `tag` API endpoints client-side. Because each endpoint ranks independently, paginated results may occasionally contain gaps or appear out of strict vote order.

## Development

No manual install step required — `uv run` handles the environment automatically.

```bash
git clone https://github.com/anomalyco/lxradio
cd lxradio
uv run lxradio
```

Or, if you prefer to skip `uv` entirely while hacking on the code:

```bash
python run.py
```

### Tests & linting

```bash
uv run pytest tests/          # run tests
uv run ruff check src/ tests/  # lint
uv run mypy src/              # type check
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and pull request guidelines.

## License

[MIT](LICENSE)

## Attribution

Station data provided by [radio-browser.info](https://www.radio-browser.info/).
