"""Tests for lxradio.renderer."""

from unittest.mock import MagicMock, patch

import pytest

from lxradio.radio_browser import Station
from lxradio.renderer import (
    _SPINNER,
    DrawState,
    Renderer,
    _safe_addstr,
    _trunc,
    _vol_bar,
    compute_layout,
)


class TestHelpers:
    def test_trunc_short(self):
        assert _trunc("hello", 10) == "hello"

    def test_trunc_long(self):
        assert _trunc("hello world", 8) == "hello w…"

    def test_trunc_zero(self):
        assert _trunc("hello", 0) == "…"

    def test_vol_bar(self):
        assert _vol_bar(50, 10) == "█████░░░░░"
        assert _vol_bar(0, 10) == "░░░░░░░░░░"
        assert _vol_bar(100, 10) == "██████████"


class TestSafeAddstr:
    @pytest.fixture
    def scr(self):
        return MagicMock()

    @pytest.fixture(autouse=True)
    def patch_curses_error(self):
        with patch("lxradio.renderer.curses") as mc:
            mc.error = Exception
            yield

    def test_suppresses_width_overflow(self, scr):
        scr.getmaxyx.return_value = (24, 10)
        scr.addstr.side_effect = Exception
        _safe_addstr(scr, 5, 0, "hello world")
        assert scr.addstr.call_count >= 1

    def test_suppresses_height_overflow(self, scr):
        scr.getmaxyx.return_value = (10, 80)
        scr.addstr.side_effect = Exception
        _safe_addstr(scr, 15, 0, "hello")
        assert scr.addstr.call_count >= 1

    def test_logs_unexpected_error(self, scr, caplog):
        scr.getmaxyx.return_value = (24, 80)
        scr.addstr.side_effect = Exception
        caplog.set_level("WARNING")
        _safe_addstr(scr, 5, 5, "hello")
        assert len(caplog.records) >= 1


class TestStationRowLayout:
    def test_compute_layout_wide(self):
        layout = compute_layout(80)
        assert layout.show_details is True
        assert layout.name_w == 30
        assert layout.country_col == 36
        assert layout.tag_col == 42
        assert layout.tag_w == 80 - 42 - 14
        assert layout.quality_right_pad == 2

    def test_compute_layout_narrow(self):
        layout = compute_layout(50)
        assert layout.show_details is False
        assert layout.name_w == 20

    def test_compute_layout_very_narrow(self):
        layout = compute_layout(20)
        assert layout.show_details is False
        assert layout.name_w == 0


class TestRenderer:
    @pytest.fixture
    def renderer(self):
        with patch("lxradio.renderer.curses") as mock_curses:
            mock_curses.color_pair.return_value = 1
            mock_curses.A_BOLD = 0
            mock_curses.A_DIM = 0
            mock_curses.A_REVERSE = 0
            scr = MagicMock()
            scr.getmaxyx.return_value = (24, 80)
            r = Renderer(scr)
            r._scr = scr
            yield r

    def _make_state(self, **kwargs):
        defaults = {
            "view_label": "STATIONS",
            "loading": False,
            "spinner_i": 0,
            "station_count": 0,
            "query": "",
            "search_mode": False,
            "stations": [],
            "cursor": 0,
            "scroll": 0,
            "now_playing": None,
            "song_title": "",
            "status_msg": "",
            "player_volume": 80,
            "player_is_muted": False,
            "player_can_control_volume": True,
            "footer_keys": "  ↑↓ navigate   Enter play/mute   F favourite   / search   Tab view   ←→ vol   m mute   q quit  ",
            "favorites": set(),
        }
        defaults.update(kwargs)
        return DrawState(**defaults)

    def test_draw_header_truncation_preserves_count_on_narrow(self, renderer):
        state = self._make_state(station_count=1, view_label="STATIONS")
        renderer._draw_header(state, 10)
        call = renderer._scr.addstr.call_args
        text = call[0][2]
        assert "(1)" in text

    def test_draw_header_loading(self, renderer):
        state = self._make_state(loading=True, spinner_i=0, view_label="STATIONS")
        renderer._draw_header(state, 80)
        call = renderer._scr.addstr.call_args
        text = call[0][2]
        assert "loading" in text
        assert _SPINNER[0] in text

    def test_draw_header_count_uses_stations(self, renderer):
        state = self._make_state(station_count=1, view_label="FAVOURITES")
        renderer._draw_header(state, 80)
        call = renderer._scr.addstr.call_args
        assert "(1)" in call[0][2]
        assert "FAVOURITES" in call[0][2]

    def test_draw_search_bar_in_search_mode(self, renderer):
        state = self._make_state(search_mode=True, query="jazz")
        renderer._draw_search_bar(state, 80)
        call = renderer._scr.addstr.call_args
        text = call[0][2]
        assert "jazz" in text
        assert "/" in text

    def test_draw_search_bar_not_in_search_mode(self, renderer):
        state = self._make_state(search_mode=False, query="previous")
        renderer._draw_search_bar(state, 80)
        call = renderer._scr.addstr.call_args
        text = call[0][2]
        assert "previous" in text

    def test_draw_station_row_selected_background(self, renderer):
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        renderer._draw_station_row(2, 80, s, True, False, False)
        calls = renderer._scr.addstr.call_args_list
        first_call = calls[0]
        assert first_call[0][2] == " " * 80

    def test_draw_now_playing_playing(self, renderer):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        state = self._make_state(
            now_playing=s, song_title="Song Title", player_can_control_volume=True
        )
        renderer._draw_now_playing(state, 24, 80)
        calls = renderer._scr.addstr.call_args_list
        texts = [c[0][2] for c in calls]
        assert any("A" in t for t in texts)
        assert any("Song Title" in t for t in texts)

    def test_draw_now_playing_not_playing_with_status(self, renderer):
        state = self._make_state(status_msg="Error occurred")
        renderer._draw_now_playing(state, 24, 80)
        calls = renderer._scr.addstr.call_args_list
        texts = [c[0][2] for c in calls]
        assert any("Not playing" in t for t in texts)
        assert any("Error occurred" in t for t in texts)

    def test_draw_footer(self, renderer):
        state = self._make_state()
        renderer._draw_footer(state, 24, 80)
        call = renderer._scr.addstr.call_args
        text = call[0][2]
        assert "navigate" in text or "↑↓" in text

    def test_draw_footer_no_volume_control(self, renderer):
        state = self._make_state(
            player_can_control_volume=False,
            footer_keys="  ↑↓ navigate   Enter play/mute   F favourite   / search   Tab view   q quit  ",
        )
        renderer._draw_footer(state, 24, 80)
        call = renderer._scr.addstr.call_args
        text = call[0][2]
        assert "vol" not in text

    def test_draw_station_list_empty_browse(self, renderer):
        state = self._make_state(stations=[], view_label="STATIONS", loading=False)
        renderer._draw_station_list(state, 24, 80)
        calls = renderer._scr.addstr.call_args_list
        texts = [c[0][2] for c in calls]
        assert any("No stations found" in t for t in texts)

    def test_draw_station_list_empty_favorites(self, renderer):
        state = self._make_state(stations=[], view_label="FAVOURITES", loading=False)
        renderer._draw_station_list(state, 24, 80)
        calls = renderer._scr.addstr.call_args_list
        texts = [c[0][2] for c in calls]
        assert any("No favourites yet" in t for t in texts)

    def test_draw_station_row_name_w_non_negative(self, renderer):
        s = Station("1", "VeryLongNameThatWouldBeTruncated", "http://a", "", [], "MP3", 0, 0)
        renderer._draw_station_row(2, 20, s, False, False, False)
        all_texts = [str(c.args[2]) for c in renderer._scr.addstr.call_args_list if len(c.args) >= 3]
        assert "…" in all_texts

    def test_setup_colors(self, renderer):
        with patch("lxradio.renderer.curses") as mock_curses:
            mock_curses.start_color = MagicMock()
            mock_curses.use_default_colors = MagicMock()
            mock_curses.init_pair = MagicMock()
            mock_curses.COLOR_WHITE = 0
            mock_curses.COLOR_CYAN = 1
            mock_curses.COLOR_GREEN = 2
            mock_curses.COLOR_BLACK = 3
            mock_curses.COLOR_BLUE = 4
            mock_curses.COLOR_MAGENTA = 5
            mock_curses.COLOR_YELLOW = 6
            r = Renderer(MagicMock())
            r._setup_colors()
            assert mock_curses.start_color.call_count >= 1
            assert mock_curses.use_default_colors.call_count >= 1
            assert mock_curses.init_pair.call_count >= 11
