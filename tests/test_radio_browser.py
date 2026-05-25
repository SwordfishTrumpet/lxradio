"""Tests for lxradio.radio_browser."""

import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from lxradio.radio_browser import (
    Station,
    _get,
    _resolve_host,
    report_click,
    search,
    search_by_name,
    search_by_tag,
    search_by_tags,
    top_stations,
)


class TestStation:
    def test_from_api_basic(self):
        data = {
            "stationuuid": "abc-123",
            "name": "Jazz FM",
            "url_resolved": "http://example.com/stream",
            "country": "US",
            "tags": "jazz,smooth,instrumental",
            "codec": "mp3",
            "bitrate": 128,
            "votes": 42,
            "favicon": "http://example.com/favicon.ico",
        }
        s = Station.from_api(data)
        assert s.id == "abc-123"
        assert s.name == "Jazz FM"
        assert s.url == "http://example.com/stream"
        assert s.country == "US"
        assert s.tags == ["jazz", "smooth", "instrumental"]
        assert s.codec == "MP3"
        assert s.bitrate == 128
        assert s.votes == 42
        assert s.favicon == "http://example.com/favicon.ico"

    def test_from_api_keeps_all_tags(self):
        data = {
            "stationuuid": "abc-123",
            "name": "Jazz FM",
            "url_resolved": "http://example.com/stream",
            "country": "US",
            "tags": "a,b,c,d,e,f,g,h",
            "codec": "mp3",
            "bitrate": 128,
            "votes": 42,
        }
        s = Station.from_api(data)
        assert s.tags == ["a", "b", "c", "d", "e", "f", "g", "h"]
        assert s.tag_str() == "a, b, c, d"

    def test_from_api_missing_fields(self):
        data = {"stationuuid": "", "name": None, "url": "http://x"}
        s = Station.from_api(data)
        assert s.name == "Unknown"
        assert s.codec == "?"
        assert s.bitrate == 0
        assert s.votes == 0
        assert s.tags == []

    def test_tag_str(self):
        s = Station("1", "X", "http://x", "", ["a", "b"], "MP3", 0, 0)
        assert s.tag_str() == "a, b"

    def test_tag_str_empty(self):
        s = Station("1", "X", "http://x", "", [], "MP3", 0, 0)
        assert s.tag_str() == "—"

    def test_tag_str_truncates(self):
        s = Station("1", "X", "http://x", "", ["a", "b", "c", "d", "e"], "MP3", 0, 0)
        assert s.tag_str() == "a, b, c, d"
        assert s.tag_str(2) == "a, b"
        assert s.tag_str(10) == "a, b, c, d, e"

    def test_quality_str_with_bitrate(self):
        s = Station("1", "X", "http://x", "", [], "MP3", 128, 0)
        assert s.quality_str == "MP3 128k"

    def test_quality_str_no_bitrate(self):
        s = Station("1", "X", "http://x", "", [], "AAC", 0, 0)
        assert s.quality_str == "AAC"


class TestResolveHost:
    @patch("lxradio.radio_browser.socket.getaddrinfo")
    @patch("lxradio.radio_browser.socket.gethostbyaddr")
    @patch("lxradio.radio_browser.time.monotonic", return_value=0.0)
    def test_resolve_and_cache(self, mock_time, mock_gethostbyaddr, mock_getaddrinfo):
        import lxradio.radio_browser as rb
        rb._cached_host = None
        rb._cached_at = 0.0
        mock_getaddrinfo.return_value = [(None, None, None, None, ("1.2.3.4",))]
        mock_gethostbyaddr.return_value = ("resolved.host", [], [])
        host = _resolve_host()
        assert host == "resolved.host"
        # second call should use cache
        host2 = _resolve_host()
        assert host2 == "resolved.host"
        mock_getaddrinfo.assert_called_once()

    @patch("lxradio.radio_browser.socket.getaddrinfo", side_effect=socket.gaierror)
    @patch("lxradio.radio_browser.time.monotonic", return_value=0.0)
    def test_resolve_fallback(self, mock_time, mock_getaddrinfo):
        import lxradio.radio_browser as rb
        rb._cached_host = None
        rb._cached_at = 0.0
        host = _resolve_host()
        assert host == "de1.api.radio-browser.info"


class TestGet:
    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_get_success(self, mock_resolve, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{"id": 1}]).encode()
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        result = _get("/test")
        assert result == [{"id": 1}]

    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_get_fallback_retry(self, mock_resolve, mock_urlopen):
        # Primary fails, first fallback succeeds
        def side_effect(req, timeout):
            if "primary.host" in req.full_url:
                raise urllib.error.URLError("timeout")
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps([{"id": 2}]).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mock_urlopen.side_effect = side_effect
        result = _get("/test")
        assert result == [{"id": 2}]
        assert mock_urlopen.call_count == 2

    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_get_all_fail(self, mock_resolve, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("fail")
        with pytest.raises(urllib.error.URLError):
            _get("/test")


class TestSearchFunctions:
    @patch("lxradio.radio_browser._get")
    def test_top_stations(self, mock_get):
        mock_get.return_value = [
            {"stationuuid": "1", "name": "A", "url_resolved": "http://a", "tags": "", "codec": "", "bitrate": 0, "votes": 0},
        ]
        result = top_stations(limit=10)
        assert len(result) == 1
        assert result[0].name == "A"
        mock_get.assert_called_once_with("/stations/topvote", {"limit": 10, "offset": 0, "hidebroken": "true"})

    @patch("lxradio.radio_browser._get")
    def test_search_by_name(self, mock_get):
        mock_get.return_value = []
        search_by_name("jazz", limit=10, offset=20)
        mock_get.assert_called_once()
        args = mock_get.call_args[0]
        assert args[1]["name"] == "jazz"
        assert args[1]["offset"] == 20

    @patch("lxradio.radio_browser._get")
    def test_search_by_tag(self, mock_get):
        mock_get.return_value = []
        search_by_tag("rock", limit=10, offset=20)
        args = mock_get.call_args[0]
        assert args[1]["tag"] == "rock"
        assert args[1]["offset"] == 20

    @patch("lxradio.radio_browser._get")
    def test_search_by_tags(self, mock_get):
        mock_get.return_value = []
        search_by_tags(["rock", "classic"], limit=10, offset=20)
        args = mock_get.call_args[0]
        assert args[1]["tagList"] == "rock,classic"
        assert args[1]["offset"] == 20

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    def test_search_merges_and_dedupes(self, mock_tag, mock_name):
        s1 = Station("1", "A", "http://a", "", ["rock"], "MP3", 128, 10)
        s2 = Station("2", "B", "http://b", "", ["rock"], "MP3", 128, 5)
        s3 = Station("3", "C", "http://c", "", ["jazz"], "MP3", 128, 20)
        # s1 appears in both name and tag results
        mock_name.return_value = [s1, s2]
        mock_tag.return_value = [s3, s1]
        result = search("rock", limit=10)
        ids = [s.id for s in result]
        assert ids == ["3", "1", "2"]
        assert len(result) == 3

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    def test_search_returns_all_merged(self, mock_tag, mock_name):
        stations = [Station(str(i), f"S{i}", f"http://{i}", "", [], "MP3", 128, i) for i in range(10)]
        mock_name.return_value = stations[:5]
        mock_tag.return_value = stations[5:]
        result = search("q", limit=3)
        assert len(result) == 3
        ids = [s.id for s in result]
        assert ids == ["9", "8", "7"]

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    def test_search_enforces_limit(self, mock_tag, mock_name):
        stations = [Station(str(i), f"S{i}", f"http://{i}", "", [], "MP3", 128, i) for i in range(10)]
        mock_name.return_value = stations[:6]
        mock_tag.return_value = stations[6:]
        result = search("q", limit=5)
        assert len(result) == 5

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    def test_search_default_limit_100(self, mock_tag, mock_name):
        search("q")
        mock_name.assert_called_once_with("q", limit=100, offset=0)
        mock_tag.assert_called_once_with("q", limit=100, offset=0)

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    def test_search_passes_offset(self, mock_tag, mock_name):
        search("q", limit=10, offset=20)
        mock_name.assert_called_once_with("q", limit=10, offset=20)
        mock_tag.assert_called_once_with("q", limit=10, offset=20)


class TestClick:
    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_click_success(self, mock_resolve, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"x"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        from lxradio.radio_browser import _click
        _click("/url/station-1")
        assert mock_urlopen.call_count == 1
        assert "primary.host" in mock_urlopen.call_args[0][0].full_url

    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_click_fallback(self, mock_resolve, mock_urlopen):
        def side_effect(req, timeout):
            if "primary.host" in req.full_url:
                raise urllib.error.URLError("timeout")
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"x"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp
        mock_urlopen.side_effect = side_effect
        from lxradio.radio_browser import _click
        _click("/url/station-1")
        assert mock_urlopen.call_count == 2


class TestReportClick:
    @patch("lxradio.radio_browser._click")
    def test_report_click(self, mock_click):
        report_click("station-1")
        mock_click.assert_called_once_with("/url/station-1")
