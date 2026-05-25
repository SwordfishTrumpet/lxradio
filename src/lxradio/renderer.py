"""Terminal UI renderer for lxradio. Pure drawing, no state mutations."""

from __future__ import annotations

import curses
import logging
import time
from dataclasses import dataclass, field
from typing import NamedTuple

from .radio_browser import Station

logger = logging.getLogger(__name__)


class C:
    NORMAL = 1
    DIM = 2
    ACCENT = 3
    PLAYING = 4
    HEADER = 5
    FOOTER = 6
    SEARCH_BOX = 7
    FAV_STAR = 8
    QUALITY = 9
    COUNTRY = 10
    TITLE_SONG = 11


_SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"


def _trunc(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: max(n - 1, 0)] + "…"


def _dim() -> int:
    return curses.color_pair(C.DIM) | curses.A_DIM


def _safe_addstr(scr: curses.window, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        scr.addstr(y, x, s, attr)
    except curses.error:
        try:
            h, w = scr.getmaxyx()
        except curses.error:
            h = w = 0
        if x >= 0 and x + len(s) >= w:
            return
        if y >= h:
            return
        logger.warning("curses.error at y=%s x=%s w=%s s=%r", y, x, w, s[:20])


def _vol_bar(vol: int, width: int = 10) -> str:
    filled = round(vol / 100 * width)
    return "█" * filled + "░" * (width - filled)


def format_time_ago(timestamp: float) -> str:
    """Return a compact relative time string."""
    diff = time.time() - timestamp
    if diff < 60:
        return "now"
    if diff < 3600:
        return f"{int(diff // 60)}m"
    if diff < 86400:
        return f"{int(diff // 3600)}h"
    return f"{int(diff // 86400)}d"


class StationRowLayout(NamedTuple):
    name_w: int
    country_col: int
    country_w: int
    tag_col: int
    tag_w: int
    quality_right_pad: int
    show_details: bool


def compute_layout(w: int) -> StationRowLayout:
    show_details = w >= 60
    gap = 2
    name_col = 5
    name_w = min(35, w // 3)
    country_w = min(15, w // 6)
    country_col = name_col + name_w + gap
    tag_col = country_col + country_w + gap
    tag_w = max(0, w - tag_col - 14)
    quality_right_pad = 2
    return StationRowLayout(name_w, country_col, country_w, tag_col, tag_w, quality_right_pad, show_details)


@dataclass(frozen=True)
class DrawState:
    view_label: str
    loading: bool
    spinner_i: int
    station_count: int
    query: str
    search_mode: bool
    stations: list[Station]
    cursor: int
    scroll: int
    now_playing: Station | None
    song_title: str
    status_msg: str
    player_volume: int
    player_is_muted: bool
    player_can_control_volume: bool
    footer_keys: str
    favorites: set[str]
    is_history_view: bool = False
    history_timestamps: list[float] = field(default_factory=list)
    sleep_remaining: float = 0.0
    sleep_fading: bool = False


class Renderer:
    """Owns all curses drawing. Receives a window handle and a read-only DrawState."""

    def __init__(self, scr: curses.window) -> None:
        self._scr = scr
        self._setup_colors()

    def _setup_colors(self) -> None:
        curses.start_color()
        curses.use_default_colors()
        bg = -1

        curses.init_pair(C.NORMAL, curses.COLOR_WHITE, bg)
        curses.init_pair(C.DIM, curses.COLOR_WHITE, bg)
        curses.init_pair(C.ACCENT, curses.COLOR_CYAN, bg)
        curses.init_pair(C.PLAYING, curses.COLOR_GREEN, bg)
        curses.init_pair(C.HEADER, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(C.FOOTER, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(C.SEARCH_BOX, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(C.FAV_STAR, curses.COLOR_YELLOW, bg)
        curses.init_pair(C.QUALITY, curses.COLOR_MAGENTA, bg)
        curses.init_pair(C.COUNTRY, curses.COLOR_YELLOW, bg)
        curses.init_pair(C.TITLE_SONG, curses.COLOR_GREEN, bg)

    def draw(self, state: DrawState) -> None:
        scr = self._scr
        scr.erase()
        h, w = scr.getmaxyx()

        self._draw_header(state, w)
        self._draw_search_bar(state, w)
        self._draw_station_list(state, h, w)
        self._draw_now_playing(state, h, w)
        self._draw_footer(state, h, w)

        scr.refresh()

    def _draw_header(self, state: DrawState, w: int) -> None:
        if state.loading:
            spinner = _SPINNER[state.spinner_i % len(_SPINNER)]
            label = f"  ◉ lxradio  ·  {state.view_label}  {spinner} loading…"
        else:
            label = f"  ◉ lxradio  ·  {state.view_label}  ({state.station_count})"
        if len(label) > w:
            label = label[-w:]
        _safe_addstr(
            self._scr,
            0,
            0,
            label.ljust(w)[:w],
            curses.color_pair(C.HEADER) | curses.A_BOLD,
        )

    def _draw_search_bar(self, state: DrawState, w: int) -> None:
        if state.search_mode:
            bar = f" / {state.query}_"
            attr = curses.color_pair(C.SEARCH_BOX) | curses.A_BOLD
        else:
            bar = f"  /{('  search…  (tag: prefix for tags)' if not state.query else '  ' + state.query)}"
            attr = _dim()
        _safe_addstr(self._scr, 1, 0, bar.ljust(w)[:w], attr)

    def _draw_station_list(self, state: DrawState, h: int, w: int) -> None:
        list_top = 2
        list_bottom = h - 4
        visible = list_bottom - list_top

        stations = state.stations
        layout = compute_layout(w)

        for row_i in range(visible):
            si = state.scroll + row_i
            y = list_top + row_i
            if si >= len(stations):
                break

            s = stations[si]
            selected = si == state.cursor
            playing = bool(state.now_playing and s.id == state.now_playing.id)
            is_fav = s.id in state.favorites
            time_str = ""
            if state.is_history_view and si < len(state.history_timestamps):
                time_str = format_time_ago(state.history_timestamps[si])

            self._draw_station_row(y, w, layout, s, selected, playing, is_fav, time_str)

        if not stations and not state.loading:
            if state.view_label == "STATIONS":
                msg = "No stations found."
            elif state.view_label == "HISTORY":
                msg = "No listening history yet."
            else:
                msg = "No favourites yet. Press F to add one."
            cy = list_top + visible // 2
            _safe_addstr(self._scr, cy, max(0, w // 2 - len(msg) // 2), msg, _dim())

    def _draw_station_row(
        self,
        y: int,
        w: int,
        layout: StationRowLayout,
        s: Station,
        selected: bool,
        playing: bool,
        is_fav: bool,
        time_str: str = "",
    ) -> None:
        scr = self._scr

        if selected:
            _safe_addstr(scr, y, 0, " " * w, curses.color_pair(C.ACCENT) | curses.A_REVERSE)

        base_attr = curses.A_REVERSE if selected else 0

        if time_str:
            _safe_addstr(scr, y, 0, _trunc(time_str, 3).rjust(3), _dim() | base_attr)
        else:
            play_sym = "▶" if playing else " "
            play_attr = (curses.color_pair(C.PLAYING) | curses.A_BOLD) if playing else _dim()
            _safe_addstr(scr, y, 1, play_sym, play_attr | base_attr)

        fav_sym = "★" if is_fav else "☆"
        fav_attr = curses.color_pair(C.FAV_STAR) | curses.A_BOLD if is_fav else _dim()
        _safe_addstr(scr, y, 3, fav_sym, fav_attr | base_attr)

        name_attr = (
            (curses.color_pair(C.ACCENT) | curses.A_BOLD) if selected else curses.color_pair(C.NORMAL)
        )
        _safe_addstr(scr, y, 5, _trunc(s.name, layout.name_w), name_attr)

        if not layout.show_details:
            return

        _safe_addstr(
            scr,
            y,
            layout.country_col,
            _trunc(s.country or "—", layout.country_w),
            curses.color_pair(C.COUNTRY) | base_attr,
        )

        _safe_addstr(
            scr,
            y,
            layout.tag_col,
            _trunc(s.tag_str(), layout.tag_w),
            _dim() | base_attr,
        )

        quality = s.quality_str
        _safe_addstr(
            scr,
            y,
            max(layout.tag_col, w - len(quality) - layout.quality_right_pad),
            quality,
            curses.color_pair(C.QUALITY) | base_attr,
        )

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

    def _draw_footer(self, state: DrawState, h: int, w: int) -> None:
        _safe_addstr(
            self._scr,
            h - 1,
            0,
            state.footer_keys.ljust(w)[:w],
            curses.color_pair(C.FOOTER),
        )
