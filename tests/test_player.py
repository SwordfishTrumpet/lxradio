"""Tests for lxradio.player."""

import contextlib
import io
import os
import signal
import subprocess
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from lxradio.player import Player


class TestPlayer:
    def test_set_volume_clamps(self):
        p = Player()
        p.set_volume(150)
        assert p.get_volume() == 100
        p.set_volume(-10)
        assert p.get_volume() == 0

    def test_set_volume_zero_mutes(self):
        p = Player()
        p.set_volume(50)
        assert not p.is_muted()
        p.set_volume(0)
        assert p.is_muted()
        assert p.get_volume() == 0

    def test_volume_up_from_muted_unmutes(self):
        p = Player()
        p.set_volume(50)
        p.toggle_mute()
        assert p.is_muted()
        assert p.get_volume() == 0
        p.volume_up()
        assert not p.is_muted()
        assert p.get_volume() == 5

    def test_volume_up_down(self):
        p = Player()
        p.set_volume(50)
        p.volume_up()
        assert p.get_volume() == 55
        p.volume_down()
        assert p.get_volume() == 50

    def test_toggle_mute(self):
        p = Player()
        p.set_volume(50)
        p.toggle_mute()
        assert p.is_muted()
        assert p.get_volume() == 0
        p.toggle_mute()
        assert not p.is_muted()
        assert p.get_volume() == 50

    def test_set_volume_unmutes(self):
        p = Player()
        p.set_volume(50)
        p.toggle_mute()
        assert p.is_muted()
        p.set_volume(30)
        assert not p.is_muted()
        assert p.get_volume() == 30

    def test_is_playing_false_initially(self):
        p = Player()
        assert not p.is_playing()

    def test_play_checks_for_mpv(self):
        p = Player()
        with patch("shutil.which", return_value=None), patch.object(p, "_on_error") as mock_error:
            result = p.play("http://stream")
            mock_error.assert_called_once_with("mpv not found in PATH")
            assert result is False

    def test_play_catches_file_not_found(self):
        p = Player()
        on_error = MagicMock()
        p._on_error = on_error
        with patch("shutil.which", return_value="/usr/bin/mpv"), patch(
            "subprocess.Popen", side_effect=FileNotFoundError
        ):
            result = p.play("http://stream")
        on_error.assert_called_once_with("mpv not found in PATH")
        assert result is False

    def test_play_catches_permission_error(self):
        p = Player()
        on_error = MagicMock()
        p._on_error = on_error
        with patch("shutil.which", return_value="/usr/bin/mpv"), patch(
            "subprocess.Popen", side_effect=PermissionError("Permission denied")
        ):
            result = p.play("http://stream")
        on_error.assert_called_once_with("Failed to start mpv: Permission denied")
        assert result is False

    def test_play_catches_os_error(self):
        p = Player()
        on_error = MagicMock()
        p._on_error = on_error
        with patch("shutil.which", return_value="/usr/bin/mpv"), patch(
            "subprocess.Popen", side_effect=OSError("Too many open files")
        ):
            result = p.play("http://stream")
        on_error.assert_called_once_with("Failed to start mpv: Too many open files")
        assert result is False

    def test_play_returns_true_on_success(self):
        p = Player()
        fake_proc = MagicMock()
        # Use an event-based iterator so the thread can be interrupted promptly
        _stop_event = threading.Event()
        class BlockingIter:
            def __iter__(self):
                return self
            def __next__(self):
                if _stop_event.wait(10):
                    raise StopIteration
                raise StopIteration
        fake_proc.stdout = BlockingIter()
        with patch("shutil.which", return_value="/usr/bin/mpv"), patch(
            "subprocess.Popen", return_value=fake_proc
        ):
            result = p.play("http://stream")
        assert result is True
        assert p._ipc_socket == f"/tmp/lxradio-mpv-{os.getpid()}.sock"
        assert p._metadata_thread is not None
        assert isinstance(p._metadata_thread, type(threading.Thread()))
        assert p._metadata_thread.is_alive()
        _stop_event.set()
        p.stop()

    def test_stop_joins_reader_thread(self):
        p = Player()
        # Create a fake process that looks alive
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.stdout = iter(["icy-title: Test Song\n"])
        fake_proc.send_signal = MagicMock()
        fake_proc.wait = MagicMock()
        fake_proc.kill = MagicMock()

        with patch("shutil.which", return_value="/usr/bin/mpv"), patch(
            "subprocess.Popen", return_value=fake_proc
        ):
            on_meta = MagicMock()
            p._on_metadata = on_meta
            p.play("http://stream")
            # Give reader a moment to start
            time.sleep(0.1)
            p.stop()
        assert p._metadata_thread is None
        fake_proc.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_stop_joins_alive_reader_thread(self):
        p = Player()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 0
        fake_proc.stdout = iter([])
        fake_proc.send_signal = MagicMock()
        fake_proc.wait = MagicMock()
        fake_proc.kill = MagicMock()

        with patch("shutil.which", return_value="/usr/bin/mpv"), patch(
            "subprocess.Popen", return_value=fake_proc
        ):
            p.play("http://stream")
        # Simulate a thread that is still alive
        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        p._metadata_thread = fake_thread
        p.stop()
        fake_thread.join.assert_called_once_with(timeout=1)
        assert p._metadata_thread is None

    def test_stop_kills_on_timeout(self):
        p = Player()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.stdout = iter([])
        fake_proc.send_signal = MagicMock()
        fake_proc.wait.side_effect = subprocess.TimeoutExpired("mpv", 2)
        fake_proc.kill = MagicMock()

        with patch("shutil.which", return_value="/usr/bin/mpv"), patch(
            "subprocess.Popen", return_value=fake_proc
        ):
            p.play("http://stream")
        p.stop()
        fake_proc.kill.assert_called_once()

    def test_metadata_parsing(self):
        p = Player()
        stdout = io.StringIO("icy-title: Hello World\n")
        fake_proc = MagicMock()
        fake_proc.stdout = stdout
        p._proc = fake_proc
        p._read_output()
        assert p.current_title == "Hello World"

    def test_metadata_parsing_title_variant(self):
        p = Player()
        stdout = io.StringIO("Title: Another Song\n")
        fake_proc = MagicMock()
        fake_proc.stdout = stdout
        p._proc = fake_proc
        p._read_output()
        assert p.current_title == "Another Song"

    def test_read_output_ignores_closed_pipe(self):
        p = Player()
        fake_proc = MagicMock()
        fake_proc.stdout = MagicMock()
        fake_proc.stdout.__iter__ = MagicMock(side_effect=ValueError("closed"))
        p._proc = fake_proc
        # Should not raise
        p._read_output()

    def test_read_output_ignores_unicode_error(self):
        p = Player()
        fake_proc = MagicMock()
        fake_proc.stdout = MagicMock()
        fake_proc.stdout.__iter__ = MagicMock(side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"))
        p._proc = fake_proc
        # Should not raise
        p._read_output()

    def test_read_output_returns_when_stdout_is_none(self):
        p = Player()
        fake_proc = MagicMock()
        fake_proc.stdout = None
        p._proc = fake_proc
        # Should return immediately without raising
        p._read_output()
        assert p.current_title == ""

    def test_system_volume_skipped_on_macos(self, monkeypatch):
        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", True)
        with patch("subprocess.run") as mock_run:
            p._system_volume(50)
        mock_run.assert_not_called()

    def test_system_volume_macos_ipc_sent(self, monkeypatch):
        import socket
        import threading

        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", True)
        sock_path = f"/tmp/lxradio-test-{os.getpid()}.sock"
        p._ipc_socket = sock_path

        # Clean up any stale socket
        with contextlib.suppress(FileNotFoundError):
            os.unlink(sock_path)

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)

        received = []

        def accept_and_verify():
            conn, _ = srv.accept()
            data = conn.recv(1024)
            received.append(data)
            conn.close()
            srv.close()

        t = threading.Thread(target=accept_and_verify)
        t.start()
        p._system_volume(75)
        t.join(timeout=2)

        assert len(received) == 1
        import json
        assert json.loads(received[0]) == {"command": ["set_property", "volume", 75]}

        with contextlib.suppress(FileNotFoundError):
            os.unlink(sock_path)

    def test_system_volume_macos_ipc_graceful_on_missing_socket(self, monkeypatch):
        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", True)
        p._ipc_socket = "/nonexistent/lxradio-mpv.sock"
        # Should not raise
        p._system_volume(50)

    def test_system_volume_linux_ipc_first(self, monkeypatch, tmp_path):
        import socket
        import threading

        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", False)
        monkeypatch.setattr("lxradio.player._has_pactl", lambda: True)
        sock_path = str(tmp_path / "mpv.sock")
        # On macOS AF_UNIX path may be too long; skip if so
        if len(sock_path) > 104:
            pytest.skip("AF_UNIX path too long")
        p._ipc_socket = sock_path

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)

        received = []

        def accept_and_verify():
            conn, _ = srv.accept()
            data = conn.recv(1024)
            received.append(data)
            conn.close()
            srv.close()

        t = threading.Thread(target=accept_and_verify)
        t.start()
        with patch("subprocess.run") as mock_run:
            p._system_volume(60)
        t.join(timeout=2)

        assert len(received) == 1
        import json
        assert json.loads(received[0]) == {"command": ["set_property", "volume", 60]}
        mock_run.assert_not_called()

    def test_system_volume_linux_fallback_to_pactl(self, monkeypatch, tmp_path):
        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", False)
        monkeypatch.setattr("lxradio.player._has_pactl", lambda: True)
        p._ipc_socket = "/nonexistent/lxradio-mpv.sock"
        with patch("subprocess.run") as mock_run:
            p._system_volume(55)
        mock_run.assert_called_once_with(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "55%"],
            check=False,
            capture_output=True,
        )

    def test_is_playing_heartbeat_timeout(self):
        p = Player()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        p._proc = fake_proc
        p._last_output_at = time.monotonic() - 60.0
        assert not p.is_playing()

    def test_is_playing_heartbeat_active(self):
        p = Player()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        p._proc = fake_proc
        p._last_output_at = time.monotonic()
        assert p.is_playing()

    def test_metadata_callback_thread_safe(self):
        p = Player()
        stdout = io.StringIO("icy-title: Song A\nicy-title: Song B\n")
        fake_proc = MagicMock()
        fake_proc.stdout = stdout
        p._proc = fake_proc
        calls = []
        p._on_metadata = lambda t: calls.append(t)
        p._read_output()
        # Both titles should be captured; thread-safe logic prevents races
        assert p.current_title == "Song B"
        assert "Song A" in calls

    def test_has_pactl_true(self):
        from lxradio.player import _has_pactl, _reset_pactl_cache
        _reset_pactl_cache()
        with patch("shutil.which", return_value="/usr/bin/pactl"):
            assert _has_pactl() is True

    def test_has_pactl_false(self):
        from lxradio.player import _has_pactl, _reset_pactl_cache
        _reset_pactl_cache()
        with patch("shutil.which", return_value=None):
            assert _has_pactl() is False

    def test_has_pactl_caches_result(self):
        from lxradio.player import _has_pactl, _reset_pactl_cache
        _reset_pactl_cache()
        with patch("shutil.which", return_value="/usr/bin/pactl"):
            assert _has_pactl() is True
        # Second call should not probe filesystem again
        with patch("shutil.which") as mock_which:
            assert _has_pactl() is True
            mock_which.assert_not_called()

    def test_can_control_volume_macos(self, monkeypatch):
        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", True)
        assert p.can_control_volume()

    def test_can_control_volume_linux_with_pactl(self, monkeypatch):
        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", False)
        monkeypatch.setattr("lxradio.player._has_pactl", lambda: True)
        assert p.can_control_volume()

    def test_can_control_volume_linux_with_ipc_socket(self, monkeypatch, tmp_path):
        import os
        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", False)
        monkeypatch.setattr("lxradio.player._has_pactl", lambda: False)
        sock_path = str(tmp_path / "mpv.sock")
        # AF_UNIX path too long on macOS; use abstract path or skip
        p._ipc_socket = sock_path
        # Socket doesn't exist yet → False
        assert not p.can_control_volume()
        # Create the socket file
        open(sock_path, "a").close()
        assert p.can_control_volume()
        os.unlink(sock_path)

    def test_can_control_volume_linux_no_pactl_no_socket(self, monkeypatch):
        p = Player()
        monkeypatch.setattr("lxradio.player._IS_MACOS", False)
        monkeypatch.setattr("lxradio.player._has_pactl", lambda: False)
        p._ipc_socket = None
        assert not p.can_control_volume()
