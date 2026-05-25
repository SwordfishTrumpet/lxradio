"""Tests for lxradio.history."""

import json
import threading
import time
from unittest.mock import patch

import pytest

from lxradio.history import History, HistoryEntry
from lxradio.radio_browser import Station


class TestHistory:
    @pytest.fixture(autouse=True)
    def clean_history(self, tmp_path, monkeypatch):
        test_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", test_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        if test_file.exists():
            test_file.unlink()
        yield
        if test_file.exists():
            test_file.unlink()

    def _make_station(self, station_id: str = "1", name: str = "A") -> Station:
        return Station(station_id, name, f"http://{station_id}", "US", ["jazz"], "MP3", 128, 10, "icon")

    def test_add_creates_file(self, tmp_path):
        h = History()
        s = self._make_station()
        h.add(s)
        assert h.all()[0].station_id == "1"
        # Atomic replace means .tmp should not exist
        assert not (tmp_path / "history.jsonl.tmp").exists()

    def test_all_returns_newest_first(self):
        h = History()
        h.add(self._make_station("1", "A"))
        time.sleep(0.01)
        h.add(self._make_station("2", "B"))
        time.sleep(0.01)
        h.add(self._make_station("3", "C"))
        entries = h.all()
        assert [e.station_id for e in entries] == ["3", "2", "1"]

    def test_cap_trims_oldest(self, monkeypatch):
        monkeypatch.setattr("lxradio.history._MAX_ENTRIES", 5)
        h = History()
        for i in range(7):
            h.add(self._make_station(str(i), f"S{i}"))
        entries = h.all()
        assert len(entries) == 5
        assert [e.station_id for e in entries] == ["6", "5", "4", "3", "2"]

    def test_load_skips_malformed_last_line(self, tmp_path, monkeypatch):
        test_file = tmp_path / "history.jsonl"
        valid = json.dumps({
            "timestamp": 1.0,
            "station_id": "1",
            "station_name": "A",
            "url": "http://a",
            "country": "US",
            "tags": [],
            "codec": "MP3",
            "bitrate": 128,
            "votes": 10,
            "favicon": "",
            "song_title": "",
        })
        test_file.write_text(valid + "\nNOT JSON")
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", test_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        h = History()
        assert len(h.all()) == 1
        assert h.all()[0].station_id == "1"

    def test_get_returns_most_recent(self):
        h = History()
        h.add(self._make_station("1", "A"), song_title="Song A")
        time.sleep(0.01)
        h.add(self._make_station("1", "A"), song_title="Song B")
        entry = h.get("1")
        assert entry is not None
        assert entry.song_title == "Song B"

    def test_get_returns_none_for_missing(self):
        h = History()
        assert h.get("missing") is None

    def test_clear_empties_file(self):
        h = History()
        h.add(self._make_station())
        h.clear()
        assert h.all() == []

    def test_corruption_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "history.jsonl"
        test_file.write_text("NOT JSON")
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", test_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            h = History()
        assert len(h.all()) == 0
        assert (tmp_path / "history.jsonl.bak").exists()
        assert "Corrupted history file" in caplog.text

    def test_corruption_in_middle_backup(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "history.jsonl"
        valid = json.dumps({
            "timestamp": 1.0,
            "station_id": "1",
            "station_name": "A",
            "url": "http://a",
            "country": "US",
            "tags": [],
            "codec": "MP3",
            "bitrate": 128,
            "votes": 10,
            "favicon": "",
            "song_title": "",
        })
        test_file.write_text(valid + "\nNOT JSON\n" + valid)
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", test_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        with caplog.at_level("ERROR"):
            h = History()
        assert len(h.all()) == 0
        assert (tmp_path / "history.jsonl.bak").exists()

    def test_thread_safety(self):
        h = History()
        errors = []

        def worker(i):
            try:
                h.add(self._make_station(str(i), f"S{i}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(h.all()) == 10

    def test_atomic_write(self, tmp_path, monkeypatch):
        test_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", test_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        h = History()
        h.add(self._make_station())
        assert not (tmp_path / "history.jsonl.tmp").exists()
        assert test_file.exists()

    def test_save_raises_on_replace_failure(self, tmp_path, monkeypatch, caplog):
        test_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", test_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        h = History()
        h.add(self._make_station())
        with patch("os.replace", side_effect=OSError("disk full")), pytest.raises(
            OSError, match="disk full"
        ), caplog.at_level("ERROR"):
            h.add(self._make_station())
        assert "Failed to save history file" in caplog.text

    def test_entry_to_station(self):
        entry = HistoryEntry(
            timestamp=1.0,
            station_id="1",
            station_name="A",
            url="http://a",
            country="US",
            tags=["jazz"],
            codec="MP3",
            bitrate=128,
            votes=10,
            favicon="icon",
            song_title="Song",
        )
        s = entry.to_station()
        assert s.id == "1"
        assert s.name == "A"
        assert s.url == "http://a"
        assert s.country == "US"
        assert s.tags == ["jazz"]
        assert s.codec == "MP3"
        assert s.bitrate == 128
        assert s.votes == 10
        assert s.favicon == "icon"

    def test_persistence(self, tmp_path, monkeypatch):
        test_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("lxradio.history._HISTORY_FILE", test_file)
        monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)
        h1 = History()
        h1.add(self._make_station("1", "A"), song_title="Song A")

        h2 = History()
        entries = h2.all()
        assert len(entries) == 1
        assert entries[0].station_id == "1"
        assert entries[0].song_title == "Song A"
