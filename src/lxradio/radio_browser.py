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
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        return cls(
            id=data.get("stationuuid", ""),
            name=(data.get("name") or "Unknown").strip(),
            url=data.get("url_resolved") or data.get("url", ""),
            country=(data.get("country") or "").strip(),
            tags=tags,
            codec=(data.get("codec") or "?").upper(),
            bitrate=int(data.get("bitrate") or 0),
            votes=int(data.get("votes") or 0),
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
    hosts = [_resolve_host(), *_FALLBACK_HOSTS]
    last_exc: Exception | None = None
    for host in hosts:
        base = f"https://{host}/json"
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        url = f"{base}{path}{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"lxradio/{__version__} (github.com/anomalyco/lxradio)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data: list[dict] = json.loads(resp.read().decode())
                return data
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    # Unreachable: at least one host is always tried, and failures set last_exc.
    raise RuntimeError("No hosts were attempted")  # pragma: no cover


def top_stations(limit: int = 60, offset: int = 0) -> list[Station]:
    data = _get(
        "/stations/topvote",
        {"limit": limit, "offset": offset, "hidebroken": "true"},
    )
    return [Station.from_api(d) for d in data if d.get("url_resolved")]


def search_by_name(query: str, limit: int = 60, offset: int = 0) -> list[Station]:
    data = _get(
        "/stations/search",
        {
            "name": query,
            "limit": limit,
            "offset": offset,
            "hidebroken": "true",
            "order": "votes",
            "reverse": "true",
        },
    )
    return [Station.from_api(d) for d in data if d.get("url_resolved")]


_search_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_search_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _search_executor
    if _search_executor is None:
        _search_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    return _search_executor


def search_by_country(country: str, limit: int = 60, offset: int = 0) -> list[Station]:
    data = _get(
        "/stations/search",
        {
            "country": country,
            "limit": limit,
            "offset": offset,
            "hidebroken": "true",
            "order": "votes",
            "reverse": "true",
        },
    )
    return [Station.from_api(d) for d in data if d.get("url_resolved")]


def search(query: str, limit: int = 100, offset: int = 0) -> list[Station]:
    """Broad search across station names, tags, and countries."""
    executor = _get_search_executor()
    future_name = executor.submit(search_by_name, query, limit=limit, offset=offset)
    future_tag = executor.submit(search_by_tag, query, limit=limit, offset=offset)
    future_country = executor.submit(search_by_country, query, limit=limit, offset=offset)

    name_results = future_name.result()
    tag_results = future_tag.result()
    country_results = future_country.result()

    seen: set[str] = set()
    merged: list[Station] = []

    for station in name_results + tag_results + country_results:
        if station.id not in seen:
            seen.add(station.id)
            merged.append(station)

    merged.sort(key=lambda s: s.votes, reverse=True)
    return merged[:limit]


def search_by_tag(tag: str, limit: int = 60, offset: int = 0) -> list[Station]:
    data = _get(
        "/stations/search",
        {
            "tag": tag,
            "limit": limit,
            "offset": offset,
            "hidebroken": "true",
            "order": "votes",
            "reverse": "true",
        },
    )
    return [Station.from_api(d) for d in data if d.get("url_resolved")]


def search_by_tags(tags: list[str], limit: int = 60, offset: int = 0) -> list[Station]:
    data = _get(
        "/stations/search",
        {
            "tagList": ",".join(tags),
            "limit": limit,
            "offset": offset,
            "hidebroken": "true",
            "order": "votes",
            "reverse": "true",
        },
    )
    return [Station.from_api(d) for d in data if d.get("url_resolved")]


def _click(path: str) -> None:
    """Fire a request and ignore the response body. Used for click tracking."""
    hosts = [_resolve_host(), *_FALLBACK_HOSTS]
    for host in hosts:
        url = f"https://{host}/json{path}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"lxradio/{__version__} (github.com/anomalyco/lxradio)",
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
