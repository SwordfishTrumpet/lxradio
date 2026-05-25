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
import time
from collections.abc import Callable

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


class Player:
    """Thin wrapper around mpv for streaming radio."""

    def __init__(
        self,
        on_metadata: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self._proc: subprocess.Popen | None = None
        self._on_metadata = on_metadata
        self._on_error = on_error
        self._metadata_thread: threading.Thread | None = None
        self._current_title: str = ""
        self._volume: int = 80
        self._pre_mute_volume: int = 80
        self._muted: bool = False
        self._lock = threading.Lock()
        self._last_output_at: float = 0.0
        self._heartbeat_timeout: float = 30.0
        self._ipc_socket: str | None = None
        self._stop_requested = threading.Event()

    def play(self, url: str) -> bool:
        if shutil.which("mpv") is None:
            if self._on_error:
                self._on_error("mpv not found in PATH")
            return False
        self.stop()
        self._ipc_socket = f"/tmp/lxradio-mpv-{os.getpid()}.sock"
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
            f"--input-ipc-server={self._ipc_socket}",
            url,
        ]
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
                self._last_output_at = time.monotonic()
        except (FileNotFoundError, PermissionError, OSError) as exc:
            msg = "mpv not found in PATH" if isinstance(exc, FileNotFoundError) else f"Failed to start mpv: {exc}"
            if self._on_error:
                self._on_error(msg)
            return False

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
            self._last_output_at = 0.0
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
            if self._proc is None or self._proc.poll() is not None:
                return False
            return not (
                self._last_output_at
                and time.monotonic() - self._last_output_at > self._heartbeat_timeout
            )

    def set_volume(self, vol: int) -> None:
        self._volume = max(0, min(100, vol))
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
            self.set_volume(self._pre_mute_volume)
            self._muted = False
        else:
            self._pre_mute_volume = self._volume
            self.set_volume(0)
            self._muted = True

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
                with self._lock:
                    self._last_output_at = time.monotonic()
                line = line.strip()
                m = _ICY_RE.search(line) or _TITLE_RE.search(line)
                if m:
                    title = m.group(1).strip()
                    notify = False
                    with self._lock:
                        if title and title != self._current_title:
                            self._current_title = title
                            notify = True
                    if notify and self._on_metadata:
                        self._on_metadata(title)
        except (ValueError, OSError, UnicodeDecodeError):
            pass
