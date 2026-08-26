import concurrent.futures
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from lxradio import __version__


@dataclass
class Station:
    id: str
    name: str
    url: str
    country: str
    tags: list[str]
    codec: str
    bitrate: int
    votes: int
    favicon: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "Station":
        raw_tags = data.get("tags", "") or ""
        if isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        else:
            # Some community entries deliver tags as a JSON list instead of a string.
            tags = [str(t).strip() for t in raw_tags if t and str(t).strip()]
        return cls(
            id=data.get("stationuuid", ""),
            name=(data.get("name") or "Unknown").strip(),
            url=data.get("url_resolved") or data.get("url", ""),
            country=(data.get("country") or "").strip(),
            tags=tags,
            codec=(data.get("codec") or "?").upper(),
            bitrate=_safe_int(data.get("bitrate")),
            votes=_safe_int(data.get("votes")),
            favicon=data.get("favicon") or "",
        )

    def tag_str(self, max_tags: int = 4) -> str:
        display_tags = self.tags[:max_tags]
        return ", ".join(display_tags) if display_tags else "—"

    @property
    def quality_str(self) -> str:
        if self.bitrate:
            return f"{self.codec} {self.bitrate}k"
        return self.codec


_FALLBACK_HOSTS = [
    "de1.api.radio-browser.info",
    "nl1.api.radio-browser.info",
    "at1.api.radio-browser.info",
]
_TIMEOUT = 8
_DNS_CACHE_TTL = 300
_DNS_FAILURE_TTL = 30


def _safe_int(value: object) -> int:
    """Coerce an API value to an int, tolerating non-numeric or missing values."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value or 0))
    except (TypeError, ValueError):
        return 0


def _stations_from_data(data: object) -> list[Station]:
    """Map an API payload to Station objects, skipping malformed records.

    A single dirty record (non-numeric bitrate, list-shaped tags, a non-dict
    item) must never blank the whole page (issue #9), and a playable record
    that only has ``url`` (no ``url_resolved``) must not be dropped. A
    non-list payload raises a clear error so the caller surfaces it as a
    friendly status instead of showing a silently empty list.
    """
    if not isinstance(data, list):
        raise ValueError("unexpected API response")
    stations: list[Station] = []
    for record in data:
        if not isinstance(record, dict):
            continue
        if not (record.get("url_resolved") or record.get("url")):
            continue
        try:
            stations.append(Station.from_api(record))
        except (KeyError, TypeError, ValueError, AttributeError):
            # Per-record tolerance: skip only the bad record.
            continue
    return stations

_cached_host: str | None = None
_cached_at: float = 0.0
_cached_failure: bool = False
_dns_lock = threading.Lock()


def _resolve_host() -> str:
    global _cached_host, _cached_at, _cached_failure
    now = time.monotonic()
    with _dns_lock:
        if _cached_host:
            ttl = _DNS_FAILURE_TTL if _cached_failure else _DNS_CACHE_TTL
            if (now - _cached_at) < ttl:
                return _cached_host
    try:
        results = socket.getaddrinfo("all.api.radio-browser.info", 443)
        if results:
            ip = str(results[0][4][0])
            host, _, _ = socket.gethostbyaddr(ip)
            with _dns_lock:
                _cached_host = host
                _cached_at = now
                _cached_failure = False
            return host
    except (socket.gaierror, socket.herror, OSError):
        pass
    with _dns_lock:
        _cached_host = _FALLBACK_HOSTS[0]
        _cached_at = now
        _cached_failure = True
    return _cached_host


def _get(path: str, params: dict | None = None) -> list[dict]:
    hosts = list(dict.fromkeys([_resolve_host(), *_FALLBACK_HOSTS]))
    with _dns_lock:
        dns_failed = _cached_failure
    if dns_failed:
        # DNS is down; trying every fallback would stall for up to 3*timeout.
        # Attempt only the resolved (cached-fallback) host (PERF-2).
        hosts = hosts[:1]
    last_exc: Exception | None = None
    for host in hosts:
        base = f"https://{host}/json"
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        url = f"{base}{path}{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"lxradio/{__version__} (github.com/SwordfishTrumpet/lxradio)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError, TypeError) as exc:
            # Network-layer AND content-layer failures are retryable host
            # failures (issue #10): a non-JSON body (proxy interstitial,
            # load-balancer error page) or undecodable payload must not bypass
            # the remaining fallback hosts.
            last_exc = exc
            continue
        if not isinstance(data, list):
            # Valid JSON but the wrong shape (e.g. a dict error envelope):
            # treat as a retryable host failure, raise only after all hosts fail.
            last_exc = ValueError("unexpected API response")
            continue
        return data
    if last_exc is not None:
        raise last_exc
    # Unreachable: at least one host is always tried, and failures set last_exc.
    raise RuntimeError("No hosts were attempted")  # pragma: no cover


def top_stations(limit: int = 60, offset: int = 0) -> list[Station]:
    data = _get(
        "/stations/topvote",
        {"limit": limit, "offset": offset, "hidebroken": "true"},
    )
    return _stations_from_data(data)


def _search_by(params: dict, limit: int, offset: int) -> list[Station]:
    """Shared search-API helper: identical params + result mapping for all search_* wrappers."""
    full = {
        "limit": limit,
        "offset": offset,
        "hidebroken": "true",
        "order": "votes",
        "reverse": "true",
    }
    full.update(params)
    data = _get("/stations/search", full)
    return _stations_from_data(data)


def search_by_name(query: str, limit: int = 60, offset: int = 0) -> list[Station]:
    return _search_by({"name": query}, limit, offset)


_search_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_search_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _search_executor
    if _search_executor is None:
        _search_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    return _search_executor


def search_by_country(country: str, limit: int = 60, offset: int = 0) -> list[Station]:
    return _search_by({"country": country}, limit, offset)


def search(query: str, limit: int = 100, offset: int = 0) -> list[Station]:
    """Broad search across station names, tags, and countries."""
    executor = _get_search_executor()
    future_name = executor.submit(search_by_name, query, limit=limit, offset=offset)
    future_tag = executor.submit(search_by_tag, query, limit=limit, offset=offset)
    future_country = executor.submit(search_by_country, query, limit=limit, offset=offset)

    sub_results: list[list[Station]] = []
    failed: list[Exception] = []
    for future in (future_name, future_tag, future_country):
        try:
            sub_results.append(future.result())
        except Exception as exc:
            # A failing sub-query must not discard the successful ones; only if
            # every sub-query fails do we surface the error to the caller.
            failed.append(exc)
    if len(failed) == 3:
        raise failed[-1]

    seen: set[str] = set()
    merged: list[Station] = []

    for station in [s for sub in sub_results for s in sub]:
        if station.id not in seen:
            seen.add(station.id)
            merged.append(station)

    merged.sort(key=lambda s: s.votes, reverse=True)
    return merged[:limit]


def search_by_tag(tag: str, limit: int = 60, offset: int = 0) -> list[Station]:
    return _search_by({"tag": tag}, limit, offset)


def search_by_tags(tags: list[str], limit: int = 60, offset: int = 0) -> list[Station]:
    return _search_by({"tagList": ",".join(tags)}, limit, offset)


def _click(path: str) -> None:
    """Fire a request and ignore the response body. Used for click tracking."""
    hosts = list(dict.fromkeys([_resolve_host(), *_FALLBACK_HOSTS]))
    with _dns_lock:
        dns_failed = _cached_failure
    if dns_failed:
        hosts = hosts[:1]
    for host in hosts:
        url = f"https://{host}/json{path}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"lxradio/{__version__} (github.com/SwordfishTrumpet/lxradio)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                # Discard a few bytes to ensure the request is sent;
                # click is registered server-side before any redirect body.
                resp.read(1)
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            continue


def report_click(station_id: str) -> None:
    """Notify the API that a station was clicked (counts as a listen)."""
    _click(f"/url/{station_id}")
