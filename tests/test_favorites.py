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
        assert len(f) == 1
        assert f.all()[0].id == "1"
        assert f.is_favorite("1")

    def test_remove(self):
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        f.add(s)
        f.remove("1")
        assert len(f) == 0
        assert not f.is_favorite("1")

    def test_toggle_adds_and_removes(self):
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        added = f.toggle(s)
        assert added is True
        added2 = f.toggle(s)
        assert added2 is False

    def test_iter(self):
        f = Favorites()
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10)
        f.add(s)
        assert list(f)[0].id == "1"

    def test_persistence(self):
        s = Station("1", "A", "http://a", "US", ["jazz"], "MP3", 128, 10, "icon")
        f1 = Favorites()
        f1.add(s)

        f2 = Favorites()
        assert len(f2) == 1
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
        assert len(f) == 0
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
        assert len(f) == 1
        assert f.all()[0].id == "1"

    def test_valid_non_list_json_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        test_file.write_text("null")
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            f = Favorites()
        assert len(f) == 0
        assert (tmp_path / "favorites.json.bak").exists()
        assert "Corrupted favorites file" in caplog.text

    def test_valid_dict_json_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        test_file.write_text('{"stations": []}')
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            f = Favorites()
        assert len(f) == 0
        assert (tmp_path / "favorites.json.bak").exists()
        assert "Corrupted favorites file" in caplog.text

    def test_valid_string_json_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "favorites.json"
        test_file.write_text('"hello"')
        monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", test_file)
        monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            f = Favorites()
        assert len(f) == 0
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
