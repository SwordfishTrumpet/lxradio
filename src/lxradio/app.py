import curses
import socket
import threading
import time
import urllib.error
from collections.abc import Callable
from enum import Enum, auto

from .favorites import Favorites
from .history import History
from .key_dispatcher import make_default_dispatcher
from .player import Player
from .radio_browser import Station, report_click, search, search_by_tag, search_by_tags, top_stations
from .renderer import DrawState, Renderer
from .sleep_timer import SleepTimer

_DNS_ERRNO = 8  # macOS: nodename nor servname provided, or not known


def _is_dns_error(e: object) -> bool:
    """True when e is a DNS-resolution failure (works on both macOS and Linux)."""
    return isinstance(e, socket.gaierror) or (
        isinstance(e, OSError) and getattr(e, "errno", None) == _DNS_ERRNO
    )


def _friendly_error(e: Exception) -> str:
    """Wrap common network errors in user-friendly messages."""
    if isinstance(e, urllib.error.URLError):
        reason = e.reason
        if _is_dns_error(reason):
            return "Network error: cannot resolve radio-browser.info (check your internet connection)"
        return f"Connection error: {reason}"
    if isinstance(e, TimeoutError):
        return "Network error: request timed out (try again)"
    if _is_dns_error(e):
        return "Network error: cannot resolve station host (check your internet connection)"
    if isinstance(e, OSError):
        return f"Connection error: {e}"
    return f"Error: {e}"


class View(Enum):
    BROWSE = auto()
    FAVORITES = auto()
    HISTORY = auto()


class RadioApp:
    def __init__(self) -> None:
        self._favorites = Favorites()
        self._history = History()
        self._player = Player(on_metadata=self._on_metadata, on_error=self._on_error, on_history=self._on_history)
        self._sleep_timer = SleepTimer(
            get_volume=lambda: self._player.get_volume(),
            set_volume=lambda v: self._player.set_volume(v),
            on_expire=self._on_sleep_expire,
        )
        self._stations: list[Station] = []
        self._cursor: int = 0
        self._scroll: int = 0
        self._query: str = ""
        self._search_mode: bool = False
        self._view: View = View.BROWSE
        self._loading: bool = False
        self._spinner_i: int = 0
        self._now_playing: Station | None = None
        self._song_title: str = ""
        self._status_msg: str = ""
        self._dirty: bool = True
        self._lock = threading.Lock()
        self._stations_offset: int = 0
        self._stations_has_more: bool = False
        self._stations_loader: Callable[[int], list[Station]] | None = None
        self._batch_size: int = 60
        self._last_click_id: str | None = None
        self._last_click_at: float = 0.0
        self._station_cache: dict[str, Station] = {}
        self._renderer: Renderer | None = None
        self._dispatcher = make_default_dispatcher()
        self._load_gen: int = 0
        self._stations_paginable: bool = True
        self._sleep_restore_volume: int | None = None
        self._history_view_cache: list[Station] | None = None
        self._history_timestamps_cache: list[float] | None = None

    _CLICK_DEBOUNCE_SECS = 3.0

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, stdscr: "curses.window") -> None:
        self._scr = stdscr
        self._renderer = Renderer(stdscr)
        curses.curs_set(0)
        stdscr.timeout(200)
        self._start_load(lambda offset: top_stations(limit=self._batch_size, offset=offset))
        while True:
            if self._dirty:
                self._renderer.draw(self._build_draw_state())
                self._dirty = False
            key = stdscr.getch()
            if self._tick(key):
                break
        self.shutdown()

    def _tick(self, key: int) -> bool:
        if key == -1:
            if self._loading:
                self._spinner_i += 1
                self._dirty = True
            return False
        quit_ = self._handle_search_key(key) if self._search_mode else self._handle_nav_key(key)
        return bool(quit_)

    def _build_draw_state(self) -> DrawState:
        h, w = self._scr.getmaxyx()
        # Reads of fields written by background threads (see AGENTS.md thread-safety
        # rules) are done under the lock.
        with self._lock:
            loading = self._loading
            spinner_i = self._spinner_i
            status_msg = self._status_msg
            now_playing = self._now_playing
            song_title = self._song_title
        history_timestamps: list[float] = []
        if self._view == View.HISTORY:
            if self._history_view_cache is None:
                entries = self._history.all()
                timestamps = [entry.timestamp for entry in entries]
                stations = [entry.to_station() for entry in entries]
                self._history_timestamps_cache = timestamps
                self._history_view_cache = stations
            else:
                stations = self._history_view_cache
            history_timestamps = self._history_timestamps_cache or []
        else:
            stations = self._current_stations()
        if self._cursor < self._scroll:
            self._scroll = self._cursor
        if self._cursor >= self._scroll + (h - 6):
            self._scroll = self._cursor - (h - 6) + 1
        view_label = "STATIONS"
        if self._view == View.FAVORITES:
            view_label = "FAVOURITES"
        elif self._view == View.HISTORY:
            view_label = "HISTORY"

        # Don't show the BROWSE search filter in other views (MINOR: stale query).
        query_for_bar = self._query
        if not self._search_mode and self._view != View.BROWSE:
            query_for_bar = ""

        return DrawState(
            view_label=view_label,
            loading=loading,
            spinner_i=spinner_i,
            station_count=len(stations),
            query=query_for_bar,
            search_mode=self._search_mode,
            stations=stations,
            cursor=self._cursor,
            scroll=self._scroll,
            now_playing=now_playing,
            song_title=song_title,
            status_msg=status_msg,
            player_volume=self._player.get_volume(),
            player_is_muted=self._player.is_muted(),
            player_can_control_volume=self._player.can_control_volume(),
            footer_keys=self._dispatcher.footer_text(self),
            favorites={s.id for s in self._favorites.all()},
            is_history_view=self._view == View.HISTORY,
            history_timestamps=history_timestamps,
            sleep_remaining=self._sleep_timer.remaining_seconds(),
            sleep_fading=self._sleep_timer.is_fading(),
        )

    def _handle_nav_key(self, key: int) -> bool:
        result = self._dispatcher.dispatch(self, key)
        self._dirty = True
        return result is True

    def _nav_up(self) -> None:
        self._cursor = max(0, self._cursor - 1)

    def _nav_down(self) -> None:
        stations = self._current_stations()
        if stations:
            self._cursor = min(len(stations) - 1, self._cursor + 1)
            self._maybe_load_more()

    def _page_up(self) -> None:
        h, _ = self._scr.getmaxyx()
        self._cursor = max(0, self._cursor - (h - 6))

    def _page_down(self) -> None:
        stations = self._current_stations()
        if stations:
            h, _ = self._scr.getmaxyx()
            self._cursor = min(len(stations) - 1, self._cursor + (h - 6))
            self._maybe_load_more()

    def _on_resize(self) -> None:
        self._dirty = True

    def _enter(self) -> None:
        stations = self._current_stations()
        if stations and self._cursor < len(stations):
            selected = stations[self._cursor]
            if self._now_playing and selected.id == self._now_playing.id:
                self._player.toggle_mute()
                self._status_msg = "Muted" if self._player.is_muted() else "Unmuted"
            else:
                self._play_selected()

    def _start_search(self) -> None:
        self._search_mode = True
        self._query = ""

    def _toggle_mute(self) -> None:
        self._player.toggle_mute()
        self._status_msg = "Muted" if self._player.is_muted() else "Unmuted"

    def _on_sleep_expire(self) -> None:
        self._player.stop()
        self._restore_volume_after_sleep()
        with self._lock:
            self._now_playing = None
            self._song_title = ""
            self._status_msg = "Sleep timer finished"
            self._dirty = True

    def _cycle_sleep_timer(self) -> None:
        result = self._sleep_timer.cycle_preset()
        if result is None:
            self._sleep_timer.cancel()
            self._restore_volume_after_sleep()
            self._status_msg = "Sleep timer off"
        else:
            label, duration = result
            self._sleep_timer.start(duration)
            self._sleep_restore_volume = self._player.get_volume()
            self._status_msg = f"Sleep timer: {label}"
        self._dirty = True

    def _cancel_sleep_timer(self) -> None:
        if self._sleep_timer.is_active():
            self._sleep_timer.cancel()
            self._restore_volume_after_sleep()
            self._status_msg = "Sleep timer cancelled"
            self._dirty = True

    def _restore_volume_after_sleep(self) -> None:
        """Undo any volume change the sleep-timer fade applied."""
        if self._sleep_restore_volume is not None:
            self._player.set_volume(self._sleep_restore_volume)
            self._sleep_restore_volume = None

    def _space(self) -> None:
        stations = self._current_stations()
        if self._player.is_playing():
            self._player.stop()
            self._sleep_timer.cancel()
            self._restore_volume_after_sleep()
            self._now_playing = None
            self._song_title = ""
            self._status_msg = "Stopped"
        elif stations:
            self._play_selected()
        else:
            self._status_msg = "No station selected"

    def _handle_search_key(self, key: int) -> bool:
        if key == 27:
            self._search_mode = False
            self._query = ""
        elif key in (curses.KEY_ENTER, 10, 13):
            self._search_mode = False
            self._cursor = 0
            self._scroll = 0
            query = self._query.strip()
            if not query:
                self._start_load(lambda offset: top_stations(limit=self._batch_size, offset=offset))
            elif query.lower().startswith("tag:"):
                tag_query = query[4:].strip()
                tags = [t.strip() for t in tag_query.split(",") if t.strip()]
                if not tags or not tag_query:
                    self._status_msg = "Empty tag query"
                elif len(tags) == 1:
                    self._start_load(lambda offset: search_by_tag(tags[0], limit=self._batch_size, offset=offset))
                else:
                    self._start_load(lambda offset: search_by_tags(tags, limit=self._batch_size, offset=offset))
            else:
                # Broad search() merges three sub-queries; offset paging is meaningless
                # after the merge, so disable infinite scroll for it (see BUG-9).
                self._start_load(
                    lambda offset: search(query, limit=self._batch_size, offset=offset),
                    paginable=False,
                )
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self._query = self._query[:-1]
        elif 32 <= key < 127:
            self._query += chr(key)
        self._dirty = True
        return False

    def _play_selected(self) -> None:
        stations = self._current_stations()
        if not stations or self._cursor >= len(stations):
            return
        station = stations[self._cursor]
        self._station_cache[station.id] = station
        self._sleep_timer.cancel()
        self._restore_volume_after_sleep()
        with self._lock:
            self._song_title, self._status_msg = "", f"Connecting to {station.name}…"
        if self._player.play(station):
            self._now_playing = station
            now = time.time()
            if station.id != self._last_click_id or (now - self._last_click_at) >= self._CLICK_DEBOUNCE_SECS:
                self._last_click_id, self._last_click_at = station.id, now
                threading.Thread(target=report_click, args=(station.id,), daemon=True).start()
        else:
            # play() already stopped any previous stream; don't leave a stale
            # "now playing" bar pointing at a dead player.
            self._now_playing = None
        self._dirty = True

    def _toggle_favorite(self) -> None:
        stations = self._current_stations()
        if not stations or self._cursor >= len(stations):
            return
        station = stations[self._cursor]
        added = self._favorites.toggle(station)
        self._status_msg = f"{'Added' if added else 'Removed'}: {station.name}"
        self._dirty = True

    def _switch_view(self, view: View) -> None:
        # Keep the BROWSE loader/alive so returning to BROWSE keeps its results
        # and can keep paging (see MINOR: stale list on view return).
        self._view, self._cursor, self._scroll, self._dirty = view, 0, 0, True

    def _start_load(self, loader: Callable[[int], list[Station]], paginable: bool = True) -> None:
        self._view = View.BROWSE
        h, _ = self._scr.getmaxyx()
        batch_size = max(max(0, h - 6) + 10, 20)
        with self._lock:
            self._load_gen += 1
            self._loading, self._stations, self._stations_offset = True, [], 0
            self._stations_has_more = paginable
            self._stations_paginable = paginable
            self._stations_loader, self._batch_size, self._cursor, self._scroll, self._dirty = loader, batch_size, 0, 0, True
        self._load_batch(0)

    def _load_batch(self, offset: int) -> None:
        with self._lock:
            loader = self._stations_loader
            gen = self._load_gen
            paginable = self._stations_paginable
            batch_size = self._batch_size

        def worker():
            results: list[Station] = []
            status_msg = ""
            try:
                if loader is not None:
                    results = loader(offset)
            except Exception as e:
                # Always surface a friendly status instead of letting the worker die.
                results, status_msg = [], _friendly_error(e)
            with self._lock:
                if gen != self._load_gen:
                    # A newer _start_load superseded this batch; drop stale results.
                    return
                existing = {s.id for s in self._stations}
                new_stations = [s for s in results if s.id not in existing]
                self._stations.extend(new_stations)
                for s in new_stations:
                    self._station_cache[s.id] = s
                self._stations_offset = offset + len(results)
                self._stations_has_more = paginable and len(results) >= batch_size
                self._loading, self._status_msg, self._dirty = False, status_msg, True

        threading.Thread(target=worker, daemon=True).start()

    def _maybe_load_more(self) -> None:
        if self._view != View.BROWSE:
            return
        with self._lock:
            if not self._stations_has_more or self._loading:
                return
            count, offset = len(self._stations), self._stations_offset
        if self._cursor >= max(0, count - 5):
            with self._lock:
                if self._loading:
                    return
                self._loading, self._dirty = True, True
            self._load_batch(offset)

    def _on_history(self, station_id: str, song_title: str) -> None:
        station = self._find_station(station_id)
        if station:
            self._history.add(station, song_title)
            self._history_view_cache = None
            self._history_timestamps_cache = None

    def _find_station(self, station_id: str) -> Station | None:
        for s in self._current_stations():
            if s.id == station_id:
                return s
        return self._station_cache.get(station_id)

    def _on_metadata(self, title: str) -> None:
        with self._lock:
            self._song_title = title
            # Only clear a transient "Connecting…" status; don't wipe a real error.
            if self._status_msg.startswith("Connecting"):
                self._status_msg = ""
            self._dirty = True

    def _on_error(self, msg: str) -> None:
        with self._lock:
            self._status_msg, self._dirty = msg, True

    def shutdown(self) -> None:
        """Stop playback and clear any pending background work."""
        self._sleep_timer.cancel()
        self._player.stop()
        with self._lock:
            self._stations_loader, self._loading = None, False

    def _current_stations(self) -> list[Station]:
        if self._view == View.FAVORITES:
            return self._favorites.all()
        if self._view == View.HISTORY:
            return [entry.to_station() for entry in self._history.all()]
        with self._lock:
            return list(self._stations)
