"""Tests for lxradio.favorites."""

import json
from unittest.mock import patch

import pytest

from lxradio.favorites import Favorites
from lxradio.radio_browser import Station


class TestFavorites:
    @pytest.fixture(autouse=True)
    def clean_favorites(self, tmp_path, monkeypatch):
        # Redirect favorites to a temp file for every test
        test_file = tmp_path / "favorites.json"
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        # Ensure clean state
        if test_file.exists():
            test_file.unlink()
        yield
        if test_file.exists():
            test_file.unlink()

    def test_add_and_all(self):
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        f.add(s)
        assert len(f.all()) == 1
        assert f.all()[0].id == "1"
        assert f.is_favorite("1")

    def test_remove(self):
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        f.add(s)
        f.remove("1")
        assert len(f.all()) == 0
        assert not f.is_favorite("1")

    def test_toggle_adds_and_removes(self):
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        added = f.toggle(s)
        assert added is True
        added2 = f.toggle(s)
        assert added2 is False

    def test_persistence(self):
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10, "icon")
        f1 = Favorites()
        f1.add(s)

        f2 = Favorites()
        assert len(f2.all()) == 1
        loaded = f2.all()[0]
        assert loaded.id == "1"
        assert loaded.favicon == "icon"

    def test_corrupted_file_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        test_file.write_text("NOT JSON")
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)

        with caplog.at_level("ERROR"):
            f = Favorites()
        assert len(f.all()) == 0
        assert (tmp_path / "favorites.json.bak").exists()
        assert "Corrupted favorites file" in caplog.text

    def test_atomic_write(self, tmp_path, monkeypatch):
        test_file = tmp_path / "favorites.json"
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        f.add(s)
        # The .tmp file should not exist after atomic replace
        assert not (tmp_path / "favorites.json.tmp").exists()
        assert test_file.exists()

    def test_single_bad_entry_does_not_nuke_all(self, tmp_path, monkeypatch):
        test_file = tmp_path / "favorites.json"
        test_file.write_text(json.dumps([
            {"id": "1", "name": "Good", "url": "http://a", "country": "US", "tags": [], "codec": "MP3", "bitrate": 128, "votes": 10},
            {"name": "Bad", "url": "http://b"},  # missing id
        ]))
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        f = Favorites()
        assert len(f.all()) == 1
        assert f.all()[0].id == "1"

    def test_valid_non_list_json_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        test_file.write_text("null")
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            f = Favorites()
        assert len(f.all()) == 0
        assert (tmp_path / "favorites.json.bak").exists()
        assert "Corrupted favorites file" in caplog.text

    def test_valid_dict_json_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        test_file.write_text('{"stations": []}')
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            f = Favorites()
        assert len(f.all()) == 0
        assert (tmp_path / "favorites.json.bak").exists()
        assert "Corrupted favorites file" in caplog.text

    def test_valid_string_json_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        test_file.write_text('"hello"')
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            f = Favorites()
        assert len(f.all()) == 0
        assert (tmp_path / "favorites.json.bak").exists()
        assert "Corrupted favorites file" in caplog.text

    def test_save_raises_on_replace_failure(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        f.add(s)
        with patch("os.replace", side_effect=OSError("disk full")), pytest.raises(
            OSError, match="disk full"
        ), caplog.at_level("ERROR"):
            f.add(s)
        assert "Failed to save favorites file" in caplog.text


    def test_uuid_less_stations_do_not_overwrite_each_other(self):
        from lxradio.radio_browser import Station as StationAPI
        f = Favorites()
        alpha = StationAPI.from_api({"name": "Alpha FM", "url": "http://a/stream"})
        beta = StationAPI.from_api({"name": "Beta Radio", "url": "http://b/stream"})
        f.add(alpha)
        f.add(beta)
        assert [s.name for s in f.all()] == ["Alpha FM", "Beta Radio"]
        # Reloading the file keeps both, with the same stable ids.
        again = Favorites()
        assert {s.id: s.name for s in again.all()} == {
            "url:http://a/stream": "Alpha FM",
            "url:http://b/stream": "Beta Radio",
        }

    def test_load_migrates_empty_saved_ids_using_the_url(self, tmp_path):
        # A favourite persisted before the fix used id "". Reloading must not
        # drop it, and two such rows must not collapse into one.
        path = tmp_path / "favorites.json"
        path.write_text(
            json.dumps([
                {"id": "", "name": "Alpha FM", "url": "http://a/stream", "country": "", "tags": [], "codec": "?", "bitrate": 0, "votes": 0, "favicon": ""},
                {"id": "", "name": "Beta Radio", "url": "http://b/stream", "country": "", "tags": [], "codec": "?", "bitrate": 0, "votes": 0, "favicon": ""},
                {"id": "abc-123", "name": "Known", "url": "http://c/stream", "country": "", "tags": [], "codec": "?", "bitrate": 0, "votes": 0, "favicon": ""},
            ])
        )
        f = Favorites()
        assert {s.id: s.name for s in f.all()} == {
            "url:http://a/stream": "Alpha FM",
            "url:http://b/stream": "Beta Radio",
            "abc-123": "Known",
        }
