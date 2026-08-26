"""Tests for lxradio.radio_browser."""

import json
import socket
import threading
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from lxradio.radio_browser import (
    Station,
    _get,
    _resolve_host,
    report_click,
    search,
    search_by_country,
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

    def test_from_api_non_numeric_bitrate(self):
        # Issue #9: community data may deliver bitrate as a non-numeric string.
        data = {"stationuuid": "1", "name": "A", "url_resolved": "http://a", "bitrate": "N/A"}
        s = Station.from_api(data)
        assert s.bitrate == 0
        assert s.url == "http://a"

    def test_from_api_bitrate_with_unit(self):
        data = {"stationuuid": "1", "name": "A", "url_resolved": "http://a", "bitrate": "128 kbps"}
        assert Station.from_api(data).bitrate == 0

    def test_from_api_tags_as_list(self):
        # Issue #9: tags may arrive as a JSON list rather than a comma string.
        data = {
            "stationuuid": "1",
            "name": "A",
            "url_resolved": "http://a",
            "tags": ["rock", "pop"],
        }
        s = Station.from_api(data)
        assert s.tags == ["rock", "pop"]

    def test_from_api_votes_non_numeric(self):
        data = {"stationuuid": "1", "name": "A", "url_resolved": "http://a", "votes": "lots"}
        assert Station.from_api(data).votes == 0

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


@pytest.fixture(autouse=True)
def _reset_dns_state():
    """Reset module-level DNS cache/failure globals so tests don't leak into each other."""
    import lxradio.radio_browser as rb
    rb._cached_host = None
    rb._cached_at = 0.0
    rb._cached_failure = False
    with rb._submissions_lock:
        rb._pending_submissions.clear()
    yield
    rb._cached_host = None
    rb._cached_at = 0.0
    rb._cached_failure = False
    with rb._submissions_lock:
        pending = list(rb._pending_submissions)
        rb._pending_submissions.clear()
    for fut in pending:
        fut.cancel()


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

    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_get_short_circuits_on_dns_failure(self, mock_resolve, mock_urlopen):
        # PERF-2: when DNS is down, only the resolved fallback host is attempted.
        import lxradio.radio_browser as rb
        rb._cached_failure = True
        mock_urlopen.side_effect = urllib.error.URLError("fail")
        with pytest.raises(urllib.error.URLError):
            _get("/test")
        assert mock_urlopen.call_count == 1

    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_get_retries_non_json_response(self, mock_resolve, mock_urlopen):
        # Issue #10: host 1 returns HTTP 200 with a non-JSON body; the
        # remaining fallback hosts must still be attempted.
        def side_effect(req, timeout):
            mock_resp = MagicMock()
            if "primary.host" in req.full_url:
                mock_resp.read.return_value = b"<html>502 Bad Gateway</html>"
            else:
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
    def test_get_all_hosts_non_json_raises(self, mock_resolve, mock_urlopen):
        # Issue #10: when every host returns a non-JSON body, the error is
        # raised only after all fallback hosts were attempted.
        def side_effect(req, timeout):
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"<html>error</html>"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mock_urlopen.side_effect = side_effect
        with pytest.raises(json.JSONDecodeError):
            _get("/test")
        assert mock_urlopen.call_count == 4

    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_get_retries_dict_shaped_response(self, mock_resolve, mock_urlopen):
        # Issue #10: valid JSON but a dict (not a list) is a retryable host
        # failure; a later host's valid list is used.
        def side_effect(req, timeout):
            mock_resp = MagicMock()
            if "primary.host" in req.full_url:
                mock_resp.read.return_value = json.dumps({"error": "envelope"}).encode()
            else:
                mock_resp.read.return_value = json.dumps([{"id": 3}]).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mock_urlopen.side_effect = side_effect
        result = _get("/test")
        assert result == [{"id": 3}]
        assert mock_urlopen.call_count == 2

    @patch("lxradio.radio_browser.urllib.request.urlopen")
    @patch("lxradio.radio_browser._resolve_host", return_value="primary.host")
    def test_get_all_hosts_dict_payload_raises(self, mock_resolve, mock_urlopen):
        # Issue #10: all hosts return a dict-shaped payload -> friendly error
        # raised only after every host was attempted.
        def side_effect(req, timeout):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"error": "envelope"}).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mock_urlopen.side_effect = side_effect
        with pytest.raises(ValueError, match="unexpected API response"):
            _get("/test")
        assert mock_urlopen.call_count == 4


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
    def test_top_stations_skips_malformed_record(self, mock_get):
        # Issue #9: one dirty record (bad bitrate / list tags) must not blank
        # the whole page; the valid records still come through.
        mock_get.return_value = [
            {"stationuuid": "1", "name": "Good", "url_resolved": "http://good", "tags": "jazz", "bitrate": 128, "votes": 5},
            {"stationuuid": "2", "name": "Dirty", "url_resolved": "http://dirty", "tags": "rock", "bitrate": "N/A", "votes": 1},
            {"stationuuid": "3", "name": "Listy", "url_resolved": "http://listy", "tags": ["pop"], "bitrate": 64, "votes": 2},
            {"stationuuid": "4", "name": "NoUrl", "url_resolved": "", "tags": "x", "bitrate": 0, "votes": 0},
        ]
        result = top_stations(limit=10)
        ids = [s.id for s in result]
        assert ids == ["1", "2", "3"]

    @patch("lxradio.radio_browser._get")
    def test_top_stations_keeps_url_only_record(self, mock_get):
        # Issue #9 comment: a record with only ``url`` (no ``url_resolved``) is
        # playable via from_api's fallback and must not be filtered out.
        mock_get.return_value = [
            {"stationuuid": "1", "name": "A", "url_resolved": "http://resolved", "tags": ""},
            {"stationuuid": "2", "name": "B", "url_resolved": "", "url": "http://direct", "tags": ""},
        ]
        result = top_stations(limit=10)
        assert [s.id for s in result] == ["1", "2"]
        assert result[1].url == "http://direct"

    @patch("lxradio.radio_browser._get")
    def test_top_stations_skips_non_dict_items(self, mock_get):
        mock_get.return_value = [
            {"stationuuid": "1", "name": "A", "url_resolved": "http://a", "tags": ""},
            "not-a-record",
            {"stationuuid": "2", "name": "B", "url_resolved": "http://b", "tags": ""},
        ]
        result = top_stations(limit=10)
        assert [s.id for s in result] == ["1", "2"]

    @patch("lxradio.radio_browser._get")
    def test_top_stations_dict_payload_raises_clear_error(self, mock_get):
        # Issue #9 DoD: a dict-shaped (non-list) JSON response must degrade to a
        # clear error (surfaced by _load_batch as a friendly status), not a
        # silently empty list.
        mock_get.return_value = {"error": "envelope"}
        with pytest.raises(ValueError, match="unexpected API response"):
            top_stations(limit=10)

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
    def test_search_by_country(self, mock_get):
        mock_get.return_value = []
        search_by_country("US", limit=10, offset=20)
        args = mock_get.call_args[0]
        assert args[1]["country"] == "US"
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
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_merges_and_dedupes(self, mock_country, mock_tag, mock_name):
        s1 = Station("1", "A", "http://a", "", ["rock"], "MP3", 128, 10)
        s2 = Station("2", "B", "http://b", "", ["rock"], "MP3", 128, 5)
        s3 = Station("3", "C", "http://c", "", ["jazz"], "MP3", 128, 20)
        # s1 appears in both name and tag results
        mock_name.return_value = [s1, s2]
        mock_tag.return_value = [s3, s1]
        mock_country.return_value = []
        result = search("rock", limit=10)
        ids = [s.id for s in result]
        assert ids == ["3", "1", "2"]
        assert len(result) == 3

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_returns_all_merged(self, mock_country, mock_tag, mock_name):
        stations = [Station(str(i), f"S{i}", f"http://{i}", "", [], "MP3", 128, i) for i in range(10)]
        mock_name.return_value = stations[:5]
        mock_tag.return_value = stations[5:]
        mock_country.return_value = []
        result = search("q", limit=3)
        assert len(result) == 3
        ids = [s.id for s in result]
        assert ids == ["9", "8", "7"]

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_enforces_limit(self, mock_country, mock_tag, mock_name):
        stations = [Station(str(i), f"S{i}", f"http://{i}", "", [], "MP3", 128, i) for i in range(10)]
        mock_name.return_value = stations[:6]
        mock_tag.return_value = stations[6:]
        mock_country.return_value = []
        result = search("q", limit=5)
        assert len(result) == 5

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_default_limit_100(self, mock_country, mock_tag, mock_name):
        search("q")
        mock_name.assert_called_once_with("q", limit=100, offset=0)
        mock_tag.assert_called_once_with("q", limit=100, offset=0)
        mock_country.assert_called_once_with("q", limit=100, offset=0)

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_partial_subquery_failure(self, mock_country, mock_tag, mock_name):
        # Issue #9: one failing sub-query must not discard the other two's results.
        s1 = Station("1", "A", "http://a", "", [], "MP3", 128, 10)
        s2 = Station("2", "B", "http://b", "", [], "MP3", 128, 5)
        mock_name.return_value = [s1]
        mock_tag.side_effect = ValueError("bad tag query")
        mock_country.return_value = [s2]
        result = search("rock", limit=10)
        ids = [s.id for s in result]
        assert ids == ["1", "2"]

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_all_subqueries_fail_raises(self, mock_country, mock_tag, mock_name):
        # Issue #9: when every sub-query fails, the error must still surface to
        # the caller (so _load_batch shows a friendly status instead of an
        # empty result list).
        exc = urllib.error.URLError("network down")
        mock_name.side_effect = exc
        mock_tag.side_effect = exc
        mock_country.side_effect = exc
        with pytest.raises(urllib.error.URLError):
            search("rock", limit=10)

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_two_fail_one_succeeds(self, mock_country, mock_tag, mock_name):
        s1 = Station("1", "A", "http://a", "", [], "MP3", 128, 10)
        mock_name.side_effect = TimeoutError("timeout")
        mock_tag.side_effect = TimeoutError("timeout")
        mock_country.return_value = [s1]
        result = search("rock", limit=10)
        assert [s.id for s in result] == ["1"]

    @patch("lxradio.radio_browser.search_by_name")
    @patch("lxradio.radio_browser.search_by_tag")
    @patch("lxradio.radio_browser.search_by_country")
    def test_search_passes_offset(self, mock_country, mock_tag, mock_name):
        search("q", limit=10, offset=20)
        mock_name.assert_called_once_with("q", limit=10, offset=20)
        mock_tag.assert_called_once_with("q", limit=10, offset=20)
        mock_country.assert_called_once_with("q", limit=10, offset=20)


class TestSearchExecutorShutdown:
    def test_submissions_run_in_daemon_threads(self):
        import lxradio.radio_browser as rb
        created = []

        class StubThread:
            def __init__(self, target=None, name=None, daemon=None):
                self.target, self.name, self.daemon = target, name, daemon
                created.append(self)

            def start(self):
                pass  # never actually run the target

        with patch("lxradio.radio_browser.threading.Thread", StubThread):
            rb._submit_in_daemon_thread(lambda: [])
        assert len(created) == 1
        thread = created[0]
        assert thread.daemon is True, "search workers must be daemon threads"
        assert callable(thread.target)

    def test_cancel_pending_searches_prevents_execution(self):
        # Issue #15: work queued but not yet started must be cancellable on quit.
        import lxradio.radio_browser as rb
        executed = threading.Event()
        created = []

        class StubThread:
            def __init__(self, target=None, name=None, daemon=None):
                self.target, self.daemon = target, daemon
                created.append(self)

            def start(self):
                pass  # queued forever: the thread never gets to run

        with patch("lxradio.radio_browser.threading.Thread", StubThread):
            fut = rb._submit_in_daemon_thread(executed.set)
            assert len(created) == 1
            rb.cancel_pending_searches()
        assert fut.cancelled(), "unstarted submission must be cancelled"
        for stub in created:
            stub.target()  # a real thread would now bail out via set_running_or_notify_cancel
        assert not executed.is_set(), "cancelled submission must never execute"
        assert rb._pending_submissions == [], "registry must be cleared"

    def test_search_works_after_cancel(self):
        import lxradio.radio_browser as rb
        rb.cancel_pending_searches()
        with (
            patch("lxradio.radio_browser.search_by_name", return_value=[]),
            patch("lxradio.radio_browser.search_by_tag", return_value=[]),
            patch("lxradio.radio_browser.search_by_country", return_value=[]),
        ):
            assert search("q") == []


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
    def test_click_short_circuits_on_dns_failure(self, mock_resolve, mock_urlopen):
        import lxradio.radio_browser as rb
        from lxradio.radio_browser import _click
        rb._cached_failure = True
        mock_urlopen.side_effect = urllib.error.URLError("fail")
        _click("/url/1")
        assert mock_urlopen.call_count == 1

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
