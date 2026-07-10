# lxradio

<p align="center">
  <img src="docs/screenshot.png" alt="lxradio in action" width="80%">
</p>

<p align="center">
  <a href="https://github.com/SwordfishTrumpet/lxradio/actions/workflows/ci.yml">
    <img src="https://github.com/SwordfishTrumpet/lxradio/actions/workflows/ci.yml/badge.svg" alt="CI Status">
  </a>
  <a href="https://codecov.io/gh/SwordfishTrumpet/lxradio">
    <img src="https://codecov.io/gh/SwordfishTrumpet/lxradio/branch/main/graph/badge.svg" alt="Code Coverage">
  </a>
  <a href="https://github.com/SwordfishTrumpet/lxradio/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/SwordfishTrumpet/lxradio" alt="License">
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue" alt="Python Versions">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
  </a>
</p>

A minimal, fast terminal TUI radio player. Browse and search thousands of internet radio stations from [radio-browser.info](https://www.radio-browser.info/), manage favourites, track your listening history, and play streams via `mpv` — all without leaving your terminal.

---

## Table of Contents

- [About](#about)
- [Features](#features)
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Keybindings](#keybindings)
- [Search](#search)
- [Configuration](#configuration)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)
- [Attribution](#attribution)

---

## About

`lxradio` is designed for terminal-focused users who want a lightweight, keyboard-driven way to discover and play internet radio. It solves the problem of juggling browser tabs, heavy GUI players, or complex music library management by providing a single, cohesive curses-based interface that stays out of your way.

### Who is it for?

- Developers and terminal power users who live in the command line
- Users looking for a distraction-free radio experience
- Anyone who wants to explore thousands of global radio stations without installing a bloated application

---

## Features

- **Browse & Search** — Explore top-voted stations or search by name, tag, or country
- **Parallel Search** — Free-text queries hit the `name`, `tag`, and `country` endpoints concurrently via `ThreadPoolExecutor(max_workers=2)`, cutting worst-case latency from ~24s (3 sequential calls) to ~16s
- **Paginated Results** — Infinite scroll loading for both browse and search views
- **Favourites** — Bookmark stations with atomic JSON writes and automatic corruption recovery
- **Listening History** — Every station played and its song metadata is logged to `~/.config/lxradio/history.jsonl` (capped at 1000 entries, JSONL format). Accessible via `Tab` cycling
- **History Replay** — Press `Enter` on any history entry to replay the station instantly without an API call
- **App-Scoped Volume** — macOS uses mpv IPC for fully isolated volume control; Linux falls back to `pactl` when the IPC socket is unavailable
- **Sleep Timer** — Set a countdown timer (15m → 30m → 60m → Off) that fades volume gracefully in the last 60 seconds
- **Graceful Shutdown** — `SIGINT` / `SIGTERM` handlers cleanly terminate mpv child processes
- **Heartbeat Detection** — Stale or dead streams are detected automatically
- **Click Deduplication** — Rapid `Enter` presses on the same station are debounced to avoid duplicate API click-tracking requests
- **Registration-Driven Keybindings** — Adding a new shortcut is a single line of registration; footer help text is auto-generated
- **Multi-Instance Support** — IPC socket path includes the process ID (`/tmp/lxradio-mpv-{pid}.sock`), so multiple instances can run simultaneously without interfering

---

## Architecture & Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Language** | Python ≥ 3.10 (tested up to 3.14) | Core application logic |
| **UI Framework** | `curses` (stdlib) | Terminal user interface |
| **Audio Engine** | `mpv` (external binary) | Stream playback and metadata extraction |
| **Data Source** | [radio-browser.info API](https://www.radio-browser.info/) | Station directory and search |
| **Package Manager** | `uv` | Dependency sync, environment management, builds |
| **Build Backend** | `hatchling` | PEP 517 wheel/sdist building |
| **Testing** | `pytest` ≥ 9.0 + `pytest-cov` ≥ 7.0 | Unit tests with coverage |
| **Linting** | `ruff` ≥ 0.15 | Fast Python linting and formatting |
| **Type Checking** | `mypy` | Static type analysis |

### Module Structure

```
src/lxradio/
  __init__.py       — Version info and config directory constants
  __main__.py       — CLI entry point with signal handlers
  app.py            — Curses TUI state machine (RadioApp)
  renderer.py       — Pure curses drawing (Renderer, DrawState, StationRowLayout)
  key_dispatcher.py — Registration-driven input handling (KeyDispatcher, KeyBinding)
  player.py         — mpv wrapper with IPC volume control and metadata extraction
  favorites.py      — Persistent favourites manager with atomic writes
  history.py        — Persistent listening log manager (JSONL, capped at 1000 entries)
  radio_browser.py  — API client (Station, search, top stations, DNS caching)
  sleep_timer.py    — Countdown timer with proportional fade-out
```

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | ≥ 3.10 | Tested on 3.10, 3.11, 3.12, 3.13 |
| mpv | Any recent | Must be available in `PATH` |
| uv | Latest | Optional but strongly recommended |

### Installing mpv

**macOS (Homebrew):**
```bash
brew install mpv
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install mpv
```

**Linux (Fedora):**
```bash
sudo dnf install mpv
```

---

## Installation

### Option 1: Install via `uv` (Recommended)

`uv` is the fastest and most reliable way to install and manage Python tools.

```bash
# Install uv if you don't have it
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/SwordfishTrumpet/lxradio
cd lxradio

# Install as a global tool
uv tool install -e .

# Or install into the project virtual environment
uv sync
uv pip install -e .
```

> **Note:** `uv tool install` makes `lxradio` globally available in your terminal. Use `--reinstall` to update after pulling changes.

### Option 2: Install via `pip`

```bash
git clone https://github.com/SwordfishTrumpet/lxradio
cd lxradio
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Option 3: Run without installing

```bash
python run.py
```

> **Note:** `python run.py` is the recommended development workflow — it adds `src/` to `PYTHONPATH` so source changes are picked up immediately with no reinstall step.

---

## Usage

Once installed, launch from any terminal:

```bash
lxradio
```

Or from the project directory without installing:

```bash
python run.py
```

---

## Keybindings

| Key | Action |
|-----|--------|
| `↑` / `↓` or `j` / `k` | Navigate station list |
| `Enter` | Play selected station / mute current station |
| `Space` | Play/pause toggle |
| `f` | Toggle favourite for selected station |
| `m` | Mute / unmute |
| `Tab` | Cycle through Browse → Favourites → History view |
| `/` | Search by name (prefix with `tag:` for tag search) |
| `+` / `=` | Volume up |
| `-` | Volume down |
| `s` | Set sleep timer (15m → 30m → 60m → Off) |
| `S` | Cancel sleep timer |
| `q` | Quit |

### View Navigation

Pressing `Tab` cycles through three distinct views:

1. **Browse** — Top-voted stations from radio-browser.info
2. **Favourites** — Your bookmarked stations
3. **History** — Chronological log of played stations with relative timestamps

---

## Search

- **Search by name** — Type a station name and press `Enter`
- **Search by tag** — Prefix with `tag:` to search by a single tag, e.g. `tag:jazz`
- **Multi-tag search** — Use commas for multi-tag search, e.g. `tag:rock,classic`
- **Paginated results** — Scroll down to load additional results from the API

---

## Configuration

### Data Files

`lxradio` stores persistent data in your platform's config directory:

| Platform | Path |
|----------|------|
| Linux | `~/.config/lxradio/` |
| macOS | `~/.config/lxradio/` (or `$XDG_CONFIG_HOME/lxradio/`) |

### Files

| File | Format | Purpose |
|------|--------|---------|
| `favorites.json` | JSON | Bookmarked stations |
| `history.jsonl` | JSONL | Listening log (one entry per line, capped at 1000) |

### Environment Variables

| Variable | Effect |
|----------|--------|
| `XDG_CONFIG_HOME` | Overrides the default config directory path |

---

## Development

### Quick Start

No manual install step required — `uv` handles the environment automatically.

```bash
git clone https://github.com/SwordfishTrumpet/lxradio
cd lxradio
uv sync
python run.py
```

### Running Tests

```bash
uv run pytest tests/          # run all tests
uv run pytest tests/ -k NAME    # run a single test by name
```

### Linting

```bash
uv run ruff check src/ tests/
```

### Type Checking

```bash
uv run mypy src/
```

### Running the installed copy

If you prefer to use `uv run lxradio` while hacking on the code, reinstall after source changes:

```bash
uv pip install -e .
uv run lxradio
```

> **Note:** `python run.py` is the recommended dev workflow — it adds `src/` to `PYTHONPATH` so source changes are picked up immediately with no reinstall step.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and pull request guidelines.

---

## Known Limitations

- **Linux Volume:** On Linux, mpv IPC is attempted first for volume control; if the IPC socket is unavailable, `pactl` is used as a fallback. This means volume changes may still affect the global PulseAudio sink when mpv is not running or the socket is missing.
- **Merged Search Pagination:** Free-text search merges results from the `name`, `tag`, and `country` API endpoints client-side. Because each endpoint ranks independently, paginated results may occasionally contain gaps or appear out of strict vote order.

---

## License

[MIT](LICENSE)

---

## Attribution

Station data provided by [radio-browser.info](https://www.radio-browser.info/).

---

<p align="center">
  <sub>Built with <code>uv</code> · <code>mpv</code> · <code>curses</code></sub>
</p>
