import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from . import _CONFIG_DIR
from .radio_browser import Station

_ICY_RE = re.compile(r"icy-title:\s*(.+)", re.IGNORECASE)
_TITLE_RE = re.compile(r"Title:\s*(.+)", re.IGNORECASE)

_IS_MACOS = sys.platform == "darwin"

_PACTL_AVAILABLE: bool | None = None


def _has_pactl() -> bool:
    global _PACTL_AVAILABLE
    if _PACTL_AVAILABLE is None:
        _PACTL_AVAILABLE = shutil.which("pactl") is not None
    return _PACTL_AVAILABLE


def _reset_pactl_cache() -> None:
    """Reset the pactl cache. Used only in tests."""
    global _PACTL_AVAILABLE
    _PACTL_AVAILABLE = None


# AF_UNIX sun_path limit is 108 bytes on Linux and 104 on macOS/BSD; stay under both.
_SUN_PATH_MAX = 104


def _ipc_socket_path() -> str | None:
    """Return a private path for the mpv IPC socket, or None if none fits.

    The mpv IPC socket is an unauthenticated command channel: any local process
    that can connect can drive mpv, including commands that spawn programs
    (issue #22). It must therefore live in a directory other users cannot
    reach — never directly in the world-writable /tmp. Preferred locations are
    the per-user runtime directory ($XDG_RUNTIME_DIR on Linux, $TMPDIR on
    macOS, both private by platform contract), falling back to a locked-down
    subdirectory of the lxradio config dir.
    """
    base = os.environ.get("TMPDIR" if _IS_MACOS else "XDG_RUNTIME_DIR")
    candidates = [Path(base) / "lxradio"] if base else []
    candidates.append(_CONFIG_DIR / "run")
    for d in candidates:
        try:
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(d, 0o700)
        except OSError:
            continue
        path = str(d / f"mpv-{os.getpid()}.sock")
        if len(path.encode()) < _SUN_PATH_MAX:
            return path
    return None


class Player:
    """Thin wrapper around mpv for streaming radio."""

    def __init__(
        self,
        on_metadata: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_history: Callable[[str, str], None] | None = None,
    ):
        self._proc: subprocess.Popen | None = None
        self._on_metadata = on_metadata
        self._on_error = on_error
        self._on_history = on_history
        self._metadata_thread: threading.Thread | None = None
        self._current_title: str = ""
        self._current_station: Station | None = None
        self._volume: int = 80
        self._pre_mute_volume: int = 80
        self._muted: bool = False
        self._lock = threading.Lock()
        self._ipc_socket: str | None = None
        self._stop_requested = threading.Event()

    def play(self, station: Station) -> bool:
        if shutil.which("mpv") is None:
            if self._on_error:
                self._on_error("mpv not found in PATH")
            return False
        self.stop()
        self._ipc_socket = _ipc_socket_path()
        if self._ipc_socket:
            with contextlib.suppress(OSError):
                os.unlink(self._ipc_socket)
        cmd = [
            "mpv",
            "--no-video",
            "--no-terminal",
            "--really-quiet",
            f"--volume={self._volume}",
            "--msg-level=all=no,stream=info",
            "--display-tags=icy-title,title",
        ]
        if self._ipc_socket:
            cmd.append(f"--input-ipc-server={self._ipc_socket}")
        cmd.append(station.url)
        try:
            with self._lock:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    errors="replace",
                )
                self._current_title = ""
                self._current_station = station
        except (FileNotFoundError, PermissionError, OSError) as exc:
            msg = "mpv not found in PATH" if isinstance(exc, FileNotFoundError) else f"Failed to start mpv: {exc}"
            if self._on_error:
                self._on_error(msg)
            return False

        if self._on_history:
            self._on_history(station.id, "")

        self._metadata_thread = threading.Thread(
            target=self._read_output, daemon=True
        )
        self._metadata_thread.start()
        return True

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.send_signal(signal.SIGTERM)
                    self._proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    self._proc.kill()
            self._proc = None
            self._current_title = ""
            self._current_station = None
            if self._ipc_socket:
                with contextlib.suppress(OSError):
                    os.unlink(self._ipc_socket)
                self._ipc_socket = None
        if self._metadata_thread and self._metadata_thread.is_alive():
            self._metadata_thread.join(timeout=1)
        self._metadata_thread = None
        self._stop_requested.clear()

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def set_volume(self, vol: int) -> None:
        vol = max(0, min(100, vol))
        if self._volume > 0 and vol == 0:
            # Reaching zero via a direct set (volume_down / mute): remember the
            # last non-zero value so toggle_mute can restore a sensible volume.
            self._pre_mute_volume = self._volume
        self._volume = vol
        self._muted = self._volume == 0
        self._system_volume(self._volume)

    def get_volume(self) -> int:
        return self._volume

    def volume_up(self, step: int = 5) -> None:
        self.set_volume(self._volume + step)

    def volume_down(self, step: int = 5) -> None:
        self.set_volume(self._volume - step)

    def toggle_mute(self) -> None:
        if self._muted:
            target = self._pre_mute_volume if self._pre_mute_volume > 0 else 50
            self.set_volume(target)
        else:
            if self._volume > 0:
                self._pre_mute_volume = self._volume
            self.set_volume(0)

    def is_muted(self) -> bool:
        return self._muted

    def _system_volume(self, vol: int) -> None:
        if _IS_MACOS:
            self._mpv_ipc_set_volume(vol)
            return
        if self._mpv_ipc_set_volume(vol):
            return
        with contextlib.suppress(FileNotFoundError):
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"],
                check=False,
                capture_output=True,
            )

    def _mpv_ipc_set_volume(self, vol: int) -> bool:
        if not self._ipc_socket:
            return False
        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect(self._ipc_socket)
            cmd = json.dumps({"command": ["set_property", "volume", vol]}) + "\n"
            sock.sendall(cmd.encode())
            return True
        except (OSError, ConnectionRefusedError):
            return False
        finally:
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.close()

    def can_control_volume(self) -> bool:
        return (
            _IS_MACOS
            or _has_pactl()
            or bool(self._ipc_socket and os.path.exists(self._ipc_socket))
        )

    @property
    def current_title(self) -> str:
        return self._current_title

    def _read_output(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self._stop_requested.is_set():
                    break
                line = line.strip()
                m = _ICY_RE.search(line) or _TITLE_RE.search(line)
                if m:
                    title = m.group(1).strip()
                    notify_meta = False
                    notify_history = False
                    history_station_id = ""
                    with self._lock:
                        if title and title != self._current_title:
                            self._current_title = title
                            notify_meta = True
                            if self._current_station:
                                notify_history = True
                                history_station_id = self._current_station.id
                    if notify_meta and self._on_metadata:
                        self._on_metadata(title)
                    if notify_history and self._on_history:
                        self._on_history(history_station_id, title)
        except (ValueError, OSError, UnicodeDecodeError):
            pass
