"""Tests for lxradio.app."""

import curses
from unittest.mock import MagicMock, patch

import pytest

from lxradio.app import RadioApp, View
from lxradio.radio_browser import Station
from lxradio.renderer import _trunc, _vol_bar


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


class TestRadioAppLogic:
    @pytest.fixture
    def app(self, tmp_path, monkeypatch):
        test_file = tmp_path / "favorites.json"
        hist_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", hist_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        if test_file.exists():
            test_file.unlink()
        if hist_file.exists():
            hist_file.unlink()

        with patch("lxradio.app.curses") as mock_curses:
            mock_curses.KEY_UP = curses.KEY_UP
            mock_curses.KEY_DOWN = curses.KEY_DOWN
            mock_curses.KEY_PPAGE = curses.KEY_PPAGE
            mock_curses.KEY_NPAGE = curses.KEY_NPAGE
            mock_curses.KEY_RESIZE = curses.KEY_RESIZE
            mock_curses.KEY_RIGHT = curses.KEY_RIGHT
            mock_curses.KEY_LEFT = curses.KEY_LEFT
            mock_curses.KEY_ENTER = curses.KEY_ENTER
            mock_curses.KEY_BACKSPACE = curses.KEY_BACKSPACE
            a = RadioApp()
            a._scr = MagicMock()
            a._scr.getmaxyx.return_value = (24, 80)
            yield a

        if test_file.exists():
            test_file.unlink()
        if hist_file.exists():
            hist_file.unlink()

    def test_current_stations_browse(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._view = View.BROWSE
        assert len(app._current_stations()) == 1

    def test_current_stations_favorites(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._favorites.add(s)
        app._view = View.FAVORITES
        assert app._current_stations()[0].id == "1"

    def test_switch_view(self, app):
        app._view = View.BROWSE
        app._cursor = 5
        app._switch_view(View.FAVORITES)
        assert app._view == View.FAVORITES
        assert app._cursor == 0

    def test_toggle_favorite_in_browse(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._cursor = 0
        app._view = View.BROWSE
        app._toggle_favorite()
        assert app._favorites.is_favorite("1")
        app._toggle_favorite()
        assert not app._favorites.is_favorite("1")

    def test_toggle_favorite_in_favorites(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._favorites.add(s)
        app._view = View.FAVORITES
        app._cursor = 0
        app._toggle_favorite()
        assert not app._favorites.is_favorite("1")

    def test_handle_nav_key_f_in_browse(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._cursor = 0
        app._view = View.BROWSE
        result = app._handle_nav_key(ord("f"))
        assert result is False
        assert app._favorites.is_favorite("1")

    def test_handle_nav_key_f_in_favorites(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._favorites.add(s)
        app._view = View.FAVORITES
        app._cursor = 0
        result = app._handle_nav_key(ord("f"))
        assert result is False
        assert not app._favorites.is_favorite("1")

    def test_handle_nav_key_tab(self, app):
        app._view = View.BROWSE
        result = app._handle_nav_key(ord("\t"))
        assert app._view == View.FAVORITES
        assert result is False

    def test_handle_nav_key_m_mutes(self, app):
        app._player.set_volume(50)
        result = app._handle_nav_key(ord("m"))
        assert result is False
        assert app._player.is_muted()
        assert app._status_msg == "Muted"

    def test_handle_nav_key_m_unmutes(self, app):
        app._player.set_volume(50)
        app._player.toggle_mute()
        result = app._handle_nav_key(ord("m"))
        assert result is False
        assert not app._player.is_muted()
        assert app._status_msg == "Unmuted"

    def test_enter_on_playing_station_mutes(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._stations = [s]
        app._cursor = 0
        app._now_playing = s
        app._player.set_volume(50)
        with patch.object(app, "_play_selected") as mock_play:
            result = app._handle_nav_key(10)
        assert result is False
        assert app._player.is_muted()
        assert app._status_msg == "Muted"
        mock_play.assert_not_called()

    def test_enter_on_different_station_plays(self, app):
        s1 = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        s2 = Station("2", "B", "http://b", "", [], "MP3", 0, 0)
        app._stations = [s1, s2]
        app._cursor = 1
        app._now_playing = s1
        with patch.object(app._player, "play", return_value=True) as mock_play:
            result = app._handle_nav_key(10)
        assert result is False
        mock_play.assert_called_once_with(s2)
        assert app._now_playing == s2

    def test_enter_on_different_station_play_failure(self, app):
        s1 = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        s2 = Station("2", "B", "http://b", "", [], "MP3", 0, 0)
        app._stations = [s1, s2]
        app._cursor = 1
        app._now_playing = s1
        with patch.object(app._player, "play", return_value=False) as mock_play:
            result = app._handle_nav_key(10)
        assert result is False
        mock_play.assert_called_once_with(s2)
        assert app._now_playing == s1  # unchanged because play failed

    def test_nav_empty_list_no_crash(self, app):
        app._stations = []
        app._cursor = 0
        app._view = View.BROWSE
        # Down arrow on empty list should not change cursor or crash
        result = app._handle_nav_key(curses.KEY_DOWN)
        assert result is False
        assert app._cursor == 0
        # Page Down on empty list should not change cursor or crash
        result = app._handle_nav_key(curses.KEY_NPAGE)
        assert result is False
        assert app._cursor == 0

    def test_handle_nav_key_up(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._cursor = 1
        result = app._handle_nav_key(curses.KEY_UP)
        assert result is False
        assert app._cursor == 0

    def test_handle_nav_key_k(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._cursor = 1
        result = app._handle_nav_key(ord("k"))
        assert result is False
        assert app._cursor == 0

    def test_handle_nav_key_j(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0), Station("2", "B", "http://b", "", [], "MP3", 0, 0)]
        app._cursor = 0
        result = app._handle_nav_key(ord("j"))
        assert result is False
        assert app._cursor == 1

    def test_handle_nav_key_down(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0), Station("2", "B", "http://b", "", [], "MP3", 0, 0)]
        app._cursor = 0
        result = app._handle_nav_key(curses.KEY_DOWN)
        assert result is False
        assert app._cursor == 1

    def test_handle_nav_key_ppage(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)] * 20
        app._cursor = 15
        result = app._handle_nav_key(curses.KEY_PPAGE)
        assert result is False
        assert app._cursor < 15

    def test_handle_nav_key_npage(self, app):
        stations = [Station(str(i), f"S{i}", f"http://{i}", "", [], "MP3", 0, 0) for i in range(30)]
        app._stations = stations
        app._cursor = 5
        result = app._handle_nav_key(curses.KEY_NPAGE)
        assert result is False
        assert app._cursor > 5

    def test_handle_nav_key_slash_enters_search(self, app):
        result = app._handle_nav_key(ord("/"))
        assert result is False
        assert app._search_mode is True
        assert app._query == ""

    def test_handle_nav_key_space_plays_when_not_playing(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._stations = [s]
        app._cursor = 0
        with patch.object(app._player, "is_playing", return_value=False), patch.object(app._player, "play", return_value=True):
            result = app._handle_nav_key(ord(" "))
        assert result is False
        assert app._now_playing == s

    def test_handle_nav_key_enter_empty_list(self, app):
        app._stations = []
        app._cursor = 0
        result = app._handle_nav_key(10)
        assert result is False
        assert app._status_msg == ""

    def test_handle_nav_key_resize(self, app):
        result = app._handle_nav_key(curses.KEY_RESIZE)
        assert result is False
        assert app._dirty is True

    def test_handle_nav_key_plus(self, app):
        app._player.set_volume(50)
        result = app._handle_nav_key(ord("+"))
        assert result is False
        assert app._player.get_volume() == 55

    def test_handle_nav_key_equal(self, app):
        app._player.set_volume(50)
        result = app._handle_nav_key(ord("="))
        assert result is False
        assert app._player.get_volume() == 55

    def test_handle_nav_key_right(self, app):
        app._player.set_volume(50)
        result = app._handle_nav_key(curses.KEY_RIGHT)
        assert result is False
        assert app._player.get_volume() == 55

    def test_handle_nav_key_minus(self, app):
        app._player.set_volume(50)
        result = app._handle_nav_key(ord("-"))
        assert result is False
        assert app._player.get_volume() == 45

    def test_handle_nav_key_left(self, app):
        app._player.set_volume(50)
        result = app._handle_nav_key(curses.KEY_LEFT)
        assert result is False
        assert app._player.get_volume() == 45

    def test_handle_nav_key_space_stops(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._stations = [s]
        app._cursor = 0
        with patch.object(app._player, "play", return_value=True), patch.object(
            app._player, "is_playing", return_value=True
        ):
            app._handle_nav_key(10)  # Enter to start playing
        assert app._now_playing is not None
        with patch.object(app._player, "is_playing", return_value=True):
            result = app._handle_nav_key(ord(" "))
        assert result is False
        assert app._status_msg == "Stopped"

    def test_handle_nav_key_space_empty_list(self, app):
        app._stations = []
        app._cursor = 0
        result = app._handle_nav_key(ord(" "))
        assert result is False
        assert app._status_msg == "No station selected"

    def test_handle_nav_key_q_quits(self, app):
        result = app._handle_nav_key(ord("q"))
        assert result is True

    def test_handle_nav_key_shift_q_quits(self, app):
        result = app._handle_nav_key(ord("Q"))
        assert result is True

    def test_handle_search_key_escape(self, app):
        app._search_mode = True
        app._query = "jazz"
        result = app._handle_search_key(27)
        assert result is False
        assert not app._search_mode
        assert app._query == ""

    def test_handle_search_key_backspace(self, app):
        app._search_mode = True
        app._query = "jazz"
        result = app._handle_search_key(curses.KEY_BACKSPACE)
        assert result is False
        assert app._query == "jaz"

    def test_handle_search_key_char_input(self, app):
        app._search_mode = True
        app._query = "jaz"
        result = app._handle_search_key(ord("z"))
        assert result is False
        assert app._query == "jazz"

    def test_play_selected_dedupes_clicks(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._stations = [s]
        app._cursor = 0
        with patch("lxradio.app.report_click") as mock_click, patch.object(
            app._player, "play", return_value=True
        ):
            app._play_selected()
            app._play_selected()  # same station immediately
        mock_click.assert_called_once()

    def test_play_selected_allows_click_after_debounce(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._stations = [s]
        app._cursor = 0
        with patch("lxradio.app.report_click") as mock_click, patch.object(
            app._player, "play", return_value=True
        ):
            app._play_selected()
            # Simulate time passing beyond debounce window
            app._last_click_at -= 10
            app._play_selected()
        assert mock_click.call_count == 2

    def test_handle_search_key_tag_prefix(self, app):
        with patch("lxradio.app.search_by_tag") as mock_tag:
            mock_tag.return_value = []
            app._search_mode = True
            app._query = "tag:jazz"
            app._handle_search_key(10)  # Enter
            assert not app._search_mode
            mock_tag.assert_called_once_with("jazz", limit=28, offset=0)

    def test_handle_search_key_tag_list_prefix(self, app):
        with patch("lxradio.app.search_by_tags") as mock_tags:
            mock_tags.return_value = []
            app._search_mode = True
            app._query = "tag:rock,classic"
            app._handle_search_key(10)
            mock_tags.assert_called_once_with(["rock", "classic"], limit=28, offset=0)

    def test_handle_search_key_name(self, app):
        with patch("lxradio.app.search") as mock_search:
            mock_search.return_value = []
            app._search_mode = True
            app._query = "jazz"
            app._handle_search_key(10)
            mock_search.assert_called_once_with("jazz", limit=28, offset=0)

    def test_handle_search_key_empty_tag(self, app):
        app._search_mode = True
        app._query = "tag:"
        app._handle_search_key(10)
        assert not app._search_mode
        assert app._status_msg == "Empty tag query"

    def test_handle_search_key_empty_name(self, app):
        app._search_mode = True
        app._query = ""
        app._scr.getmaxyx.return_value = (24, 80)
        with patch.object(app, "_start_load") as mock_load:
            app._handle_search_key(10)
        assert not app._search_mode
        mock_load.assert_called_once()

    def test_handle_search_key_empty_name_whitespace(self, app):
        app._search_mode = True
        app._query = "   "
        app._scr.getmaxyx.return_value = (24, 80)
        with patch.object(app, "_start_load") as mock_load:
            app._handle_search_key(10)
        assert not app._search_mode
        mock_load.assert_called_once()

    def test_handle_search_key_empty_tag_whitespace(self, app):
        app._search_mode = True
        app._query = "tag:   "
        app._handle_search_key(10)
        assert not app._search_mode
        assert app._status_msg == "Empty tag query"

    def test_handle_search_key_all_empty_tags(self, app):
        app._search_mode = True
        app._query = "tag:,,,"
        app._handle_search_key(10)
        assert not app._search_mode
        assert app._status_msg == "Empty tag query"

    def test_on_error(self, app):
        app._on_error("something broke")
        assert app._status_msg == "something broke"

    def test_load_batch_error_sets_status(self, app):
        import urllib.error
        app._scr.getmaxyx.return_value = (24, 80)
        app._start_load(lambda offset: [])
        with patch.object(app, "_stations_loader", side_effect=urllib.error.URLError("network down")):
            app._load_batch(0)
        # Worker runs in background; give it a moment
        import time
        time.sleep(0.1)
        assert "Error:" in app._status_msg

    def test_maybe_load_more_triggers(self, app):
        app._scr.getmaxyx.return_value = (24, 80)
        stations = [Station(str(i), f"S{i}", f"http://{i}", "", [], "MP3", 0, 0) for i in range(30)]
        app._stations = stations
        app._stations_has_more = True
        app._loading = False
        app._cursor = 25  # near bottom
        with patch.object(app, "_load_batch") as mock_load:
            app._maybe_load_more()
        mock_load.assert_called_once()

    def test_maybe_load_more_respects_no_more(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._stations_has_more = False
        app._loading = False
        app._cursor = 0
        with patch.object(app, "_load_batch") as mock_load:
            app._maybe_load_more()
        mock_load.assert_not_called()

    def test_maybe_load_more_respects_loading(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._stations_has_more = True
        app._loading = True
        app._cursor = 0
        with patch.object(app, "_load_batch") as mock_load:
            app._maybe_load_more()
        mock_load.assert_not_called()

    def test_maybe_load_more_favorites_early_return(self, app):
        app._view = View.FAVORITES
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._stations_has_more = True
        app._loading = False
        app._cursor = 0
        with patch.object(app, "_load_batch") as mock_load:
            app._maybe_load_more()
        mock_load.assert_not_called()

    def test_maybe_load_more_race_guard_with_fake_lock(self, app):
        """Test the real _maybe_load_more against a fake lock that flips _loading."""
        stations = [Station(str(i), f"S{i}", f"http://{i}", "", [], "MP3", 0, 0) for i in range(30)]
        app._stations = stations
        app._stations_has_more = True
        app._loading = False
        app._cursor = 25

        class RaceLock:
            """A fake lock that flips _loading to True on __exit__."""
            def __enter__(self):
                return self
            def __exit__(self, *args):
                app._loading = True
                return False

        original_lock = app._lock
        app._lock = RaceLock()
        with patch.object(app, "_load_batch") as mock_load:
            app._maybe_load_more()
        app._lock = original_lock
        mock_load.assert_not_called()

    def test_play_selected_empty_stations(self, app):
        app._stations = []
        app._cursor = 0
        with patch.object(app._player, "play") as mock_play:
            app._play_selected()
        mock_play.assert_not_called()

    def test_play_selected_cursor_out_of_bounds(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._cursor = 5
        with patch.object(app._player, "play") as mock_play:
            app._play_selected()
        mock_play.assert_not_called()

    def test_toggle_favorite_empty_stations(self, app):
        app._stations = []
        app._cursor = 0
        app._toggle_favorite()
        assert app._status_msg == ""

    def test_toggle_favorite_cursor_out_of_bounds(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._cursor = 5
        app._toggle_favorite()
        assert app._status_msg == ""

    def test_on_metadata(self, app):
        app._song_title = ""
        app._status_msg = "Loading..."
        app._on_metadata("Song Title")
        assert app._song_title == "Song Title"
        assert app._status_msg == ""
        assert app._dirty is True

    def test_shutdown_stops_player(self, app):
        with patch.object(app._player, "stop") as mock_stop:
            app.shutdown()
        mock_stop.assert_called_once()

    def test_shutdown_clears_loader(self, app):
        app._stations_loader = lambda offset: []
        app._loading = True
        with patch.object(app._player, "stop"):
            app.shutdown()
        assert app._stations_loader is None
        assert app._loading is False

    def test_tick_quits_on_q(self, app):
        assert app._tick(ord("q")) is True

    def test_tick_noop_on_no_input(self, app):
        app._loading = True
        app._spinner_i = 0
        assert app._tick(-1) is False
        assert app._spinner_i == 1
        assert app._dirty is True

    def test_tick_navigates_up(self, app):
        app._stations = [Station("1", "A", "http://a", "", [], "MP3", 0, 0)]
        app._cursor = 1
        assert app._tick(curses.KEY_UP) is False
        assert app._cursor == 0

    def test_tick_navigates_down(self, app):
        app._stations = [
            Station("1", "A", "http://a", "", [], "MP3", 0, 0),
            Station("2", "B", "http://b", "", [], "MP3", 0, 0),
        ]
        app._cursor = 0
        assert app._tick(curses.KEY_DOWN) is False
        assert app._cursor == 1

    def test_tick_enters_search(self, app):
        assert app._tick(ord("/")) is False
        assert app._search_mode is True
        assert app._query == ""

    def test_tick_search_escape(self, app):
        app._search_mode = True
        app._query = "jazz"
        assert app._tick(27) is False
        assert not app._search_mode
        assert app._query == ""

    def test_tick_search_submit(self, app):
        with patch("lxradio.app.search") as mock_search:
            mock_search.return_value = []
            app._search_mode = True
            app._query = "jazz"
            assert app._tick(curses.KEY_ENTER) is False
            assert not app._search_mode
            mock_search.assert_called_once_with("jazz", limit=28, offset=0)

    def test_tick_space_stops_when_playing(self, app):
        s = Station("1", "A", "http://a", "", [], "MP3", 0, 0)
        app._stations = [s]
        app._cursor = 0
        with patch.object(app._player, "play", return_value=True), patch.object(
            app._player, "is_playing", return_value=True
        ):
            app._tick(curses.KEY_ENTER)  # Enter to start playing
        assert app._now_playing is not None
        with patch.object(app._player, "is_playing", return_value=True):
            assert app._tick(ord(" ")) is False
        assert app._status_msg == "Stopped"

    def test_tick_mute_toggle(self, app):
        app._player.set_volume(50)
        assert app._tick(ord("m")) is False
        assert app._player.is_muted()
        assert app._status_msg == "Muted"

    def test_tab_cycles_through_views(self, app):
        app._view = View.BROWSE
        app._handle_nav_key(ord("\t"))
        assert app._view == View.FAVORITES
        app._handle_nav_key(ord("\t"))
        assert app._view == View.HISTORY
        app._handle_nav_key(ord("\t"))
        assert app._view == View.BROWSE

    def test_history_view_shows_history_entries(self, app):
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        app._history.add(s, song_title="Song A")
        app._view = View.HISTORY
        stations = app._current_stations()
        assert len(stations) == 1
        assert stations[0].id == "1"

    def test_enter_in_history_plays_station(self, app):
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        app._history.add(s, song_title="Song A")
        app._view = View.HISTORY
        app._cursor = 0
        with patch.object(app._player, "play", return_value=True) as mock_play:
            app._enter()
        mock_play.assert_called_once()
        played_station = mock_play.call_args[0][0]
        assert played_station.id == "1"

    def test_history_callback_adds_entry(self, app):
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        app._station_cache["1"] = s
        app._on_history("1", "Song A")
        entries = app._history.all()
        assert len(entries) == 1
        assert entries[0].station_id == "1"
        assert entries[0].song_title == "Song A"

    def test_history_view_empty_message(self, app):
        app._view = View.HISTORY
        state = app._build_draw_state()
        assert state.view_label == "HISTORY"
        assert state.station_count == 0

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
        with patch.object(app._player, "is_playing", return_value=True):
            app._cycle_sleep_timer()
            assert app._sleep_timer.is_active()
            app._space()
        assert not app._sleep_timer.is_active()
