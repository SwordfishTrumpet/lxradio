import contextlib
import json
import logging
import os
import shutil
from collections.abc import Iterator

from . import _CONFIG_DIR
from .radio_browser import Station

logger = logging.getLogger(__name__)

_FAVORITES_FILE = _CONFIG_DIR / "favorites.json"


class Favorites:
    def __init__(self) -> None:
        self._stations: dict[str, Station] = {}
        self._load()

    def add(self, station: Station) -> None:
        self._stations[station.id] = station
        self._save()

    def remove(self, station_id: str) -> None:
        self._stations.pop(station_id, None)
        self._save()

    def toggle(self, station: Station) -> bool:
        if station.id in self._stations:
            self.remove(station.id)
            return False
        self.add(station)
        return True

    def is_favorite(self, station_id: str) -> bool:
        return station_id in self._stations

    def all(self) -> list[Station]:
        return list(self._stations.values())

    def __len__(self) -> int:
        return len(self._stations)

    def __iter__(self) -> Iterator[Station]:
        return iter(self._stations.values())

    def _save(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "country": s.country,
                "tags": s.tags,
                "codec": s.codec,
                "bitrate": s.bitrate,
                "votes": s.votes,
                "favicon": s.favicon,
            }
            for s in self._stations.values()
        ]
        tmp = _FAVORITES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        try:
            os.replace(tmp, _FAVORITES_FILE)
        except OSError as exc:
            logger.error("Failed to save favorites file (%s): %s", _FAVORITES_FILE, exc)
            raise

    def _load(self) -> None:
        if not _FAVORITES_FILE.exists():
            return
        try:
            data = json.loads(_FAVORITES_FILE.read_text())
            if not isinstance(data, list):
                raise TypeError(f"Expected a list, got {type(data).__name__}")
            for item in data:
                try:
                    s = Station(
                        id=item["id"],
                        name=item["name"],
                        url=item["url"],
                        country=item.get("country", ""),
                        tags=item.get("tags", []),
                        codec=item.get("codec", "?"),
                        bitrate=item.get("bitrate", 0),
                        votes=item.get("votes", 0),
                        favicon=item.get("favicon", ""),
                    )
                    self._stations[s.id] = s
                except (KeyError, TypeError) as exc:
                    logger.warning("Skipping malformed favorite entry: %s", exc)
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
            backup = _FAVORITES_FILE.with_suffix(".json.bak")
            with contextlib.suppress(OSError):
                shutil.copy2(_FAVORITES_FILE, backup)
            logger.error("Corrupted favorites file (%s); backup saved to %s: %s", _FAVORITES_FILE, backup, exc)
