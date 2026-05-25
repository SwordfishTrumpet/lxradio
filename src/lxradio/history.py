import contextlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass

from . import _CONFIG_DIR
from .radio_browser import Station

logger = logging.getLogger(__name__)

_HISTORY_FILE = _CONFIG_DIR / "history.jsonl"
_MAX_ENTRIES = 1000


@dataclass(frozen=True)
class HistoryEntry:
    timestamp: float
    station_id: str
    station_name: str
    url: str
    country: str
    tags: list[str]
    codec: str
    bitrate: int
    votes: int
    favicon: str
    song_title: str

    def to_station(self) -> Station:
        return Station(
            id=self.station_id,
            name=self.station_name,
            url=self.url,
            country=self.country,
            tags=list(self.tags),
            codec=self.codec,
            bitrate=self.bitrate,
            votes=self.votes,
            favicon=self.favicon,
        )

    @classmethod
    def from_station(cls, station: Station, song_title: str = "") -> "HistoryEntry":
        return cls(
            timestamp=0.0,
            station_id=station.id,
            station_name=station.name,
            url=station.url,
            country=station.country,
            tags=list(station.tags),
            codec=station.codec,
            bitrate=station.bitrate,
            votes=station.votes,
            favicon=station.favicon,
            song_title=song_title,
        )

    def with_timestamp(self, timestamp: float) -> "HistoryEntry":
        return HistoryEntry(
            timestamp=timestamp,
            station_id=self.station_id,
            station_name=self.station_name,
            url=self.url,
            country=self.country,
            tags=list(self.tags),
            codec=self.codec,
            bitrate=self.bitrate,
            votes=self.votes,
            favicon=self.favicon,
            song_title=self.song_title,
        )


class History:
    def __init__(self) -> None:
        self._entries: list[HistoryEntry] = []
        self._lock = threading.Lock()
        self._load()

    def add(self, station: Station, song_title: str = "") -> None:
        entry = HistoryEntry(
            timestamp=time.time(),
            station_id=station.id,
            station_name=station.name,
            url=station.url,
            country=station.country,
            tags=list(station.tags),
            codec=station.codec,
            bitrate=station.bitrate,
            votes=station.votes,
            favicon=station.favicon,
            song_title=song_title,
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > _MAX_ENTRIES:
                self._entries = self._entries[-_MAX_ENTRIES:]
            self._save()

    def all(self) -> list[HistoryEntry]:
        with self._lock:
            return list(reversed(self._entries))

    def get(self, station_id: str) -> HistoryEntry | None:
        with self._lock:
            for entry in reversed(self._entries):
                if entry.station_id == station_id:
                    return entry
            return None

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._save()

    def _save(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _HISTORY_FILE.with_suffix(".jsonl.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                for entry in self._entries:
                    line = json.dumps(
                        {
                            "timestamp": entry.timestamp,
                            "station_id": entry.station_id,
                            "station_name": entry.station_name,
                            "url": entry.url,
                            "country": entry.country,
                            "tags": entry.tags,
                            "codec": entry.codec,
                            "bitrate": entry.bitrate,
                            "votes": entry.votes,
                            "favicon": entry.favicon,
                            "song_title": entry.song_title,
                        },
                        ensure_ascii=False,
                    )
                    f.write(line + "\n")
            os.replace(tmp, _HISTORY_FILE)
        except OSError as exc:
            logger.error("Failed to save history file (%s): %s", _HISTORY_FILE, exc)
            raise

    def _load(self) -> None:
        if not _HISTORY_FILE.exists():
            return
        try:
            raw = _HISTORY_FILE.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._backup_and_reset(exc)
            return

        lines = raw.splitlines()
        entries: list[HistoryEntry] = []
        had_content = False
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            had_content = True
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                if i == len(lines) - 1 and entries:
                    logger.warning("Skipping malformed last line in history file: %s", exc)
                    continue
                # Malformed line in the middle, or first/only line invalid: treat whole file as corrupted
                self._backup_and_reset(exc)
                return
            try:
                entry = HistoryEntry(
                    timestamp=float(data.get("timestamp", 0)),
                    station_id=data.get("station_id", ""),
                    station_name=data.get("station_name", ""),
                    url=data.get("url", ""),
                    country=data.get("country", ""),
                    tags=data.get("tags", []),
                    codec=data.get("codec", "?"),
                    bitrate=int(data.get("bitrate", 0)),
                    votes=int(data.get("votes", 0)),
                    favicon=data.get("favicon", ""),
                    song_title=data.get("song_title", ""),
                )
                entries.append(entry)
            except (KeyError, TypeError, ValueError) as exc:
                if i == len(lines) - 1 and entries:
                    logger.warning("Skipping malformed last line in history file: %s", exc)
                    continue
                self._backup_and_reset(exc)
                return

        if had_content and not entries:
            # File had non-empty lines but none were valid
            self._backup_and_reset(json.JSONDecodeError("No valid entries", doc=raw, pos=0))
            return

        if len(entries) > _MAX_ENTRIES:
            entries = entries[-_MAX_ENTRIES:]
        self._entries = entries

    def _backup_and_reset(self, exc: Exception) -> None:
        backup = _HISTORY_FILE.with_suffix(".jsonl.bak")
        with contextlib.suppress(OSError):
            shutil.copy2(_HISTORY_FILE, backup)
        logger.error("Corrupted history file (%s); backup saved to %s: %s", _HISTORY_FILE, backup, exc)
        self._entries = []
