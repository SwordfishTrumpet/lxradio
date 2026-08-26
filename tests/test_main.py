"""Tests for lxradio.__main__."""

import signal
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from lxradio.__main__ import main
from lxradio.app import RadioApp


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Run main() with a real RadioApp, mocked curses and redirected config.

    Returns (app, handlers) where handlers maps signum -> the registered
    handler function captured from the patched signal.signal calls.
    """
    monkeypatch.setattr("lxradio.favorites._FAVORITES_FILE", tmp_path / "favorites.json")
    monkeypatch.setattr("lxradio.favorites._CONFIG_DIR", tmp_path)
    monkeypatch.setattr("lxradio.history._HISTORY_FILE", tmp_path / "history.jsonl")
    monkeypatch.setattr("lxradio.history._CONFIG_DIR", tmp_path)

    handlers = {}

    def fake_signal(signum, handler):
        handlers[signum] = handler

    monkeypatch.setattr("lxradio.__main__.signal.signal", fake_signal)
    monkeypatch.setattr("lxradio.__main__.logging.basicConfig", MagicMock())
    return handlers


class TestMain:
    @patch("lxradio.__main__.signal.signal")
    @patch("lxradio.__main__.logging.basicConfig")
    @patch("lxradio.__main__.RadioApp")
    def test_main_sets_up_logging_and_signals(self, mock_app_cls, mock_log, mock_signal):
        mock_app = MagicMock()
        mock_app_cls.return_value = mock_app
        main()
        mock_log.assert_called_once()
        assert mock_signal.call_count == 2
        assert mock_signal.call_args_list[0][0][0] == signal.SIGINT
        assert mock_signal.call_args_list[1][0][0] == signal.SIGTERM
        mock_app.run.assert_called_once()

    @patch("lxradio.__main__.signal.signal")
    @patch("lxradio.__main__.logging.basicConfig")
    @patch("lxradio.__main__.RadioApp")
    def test_signal_handler_raises_system_exit_without_cleanup(self, mock_app_cls, mock_log, mock_signal):
        """The handler must not run lock-acquiring cleanup itself (issue #18)."""
        mock_app = MagicMock()
        mock_app_cls.return_value = mock_app
        main()
        handler = mock_signal.call_args_list[0][0][1]
        with pytest.raises(SystemExit) as exc_info:
            handler(signal.SIGINT, None)
        assert exc_info.value.code == 0
        # Cleanup is deferred to the finally in main(); the handler itself
        # performs none (shutdown was only invoked by main()'s finally).
        assert mock_app.shutdown.call_count == 1

    @patch("lxradio.__main__.signal.signal")
    @patch("lxradio.__main__.logging.basicConfig")
    @patch("lxradio.__main__.RadioApp")
    def test_main_runs_shutdown_after_normal_exit(self, mock_app_cls, mock_log, mock_signal):
        mock_app = MagicMock()
        mock_app_cls.return_value = mock_app
        main()
        mock_app.shutdown.assert_called_once()

    @patch("lxradio.__main__.signal.signal")
    @patch("lxradio.__main__.logging.basicConfig")
    @patch("lxradio.__main__.RadioApp")
    def test_main_runs_shutdown_when_run_raises_system_exit(self, mock_app_cls, mock_log, mock_signal):
        """SystemExit from the signal handler unwinds through main()'s finally."""
        mock_app = MagicMock()
        mock_app.run.side_effect = SystemExit(0)
        mock_app_cls.return_value = mock_app
        with pytest.raises(SystemExit):
            main()
        mock_app.shutdown.assert_called_once()


class TestSignalDeadlockRegression:
    """Issue #18: SIGINT/SIGTERM delivered while the main thread holds a
    non-reentrant lock used to self-deadlock inside the handler. The handler
    now only raises SystemExit; shutdown runs after the frame unwound."""

    def _lock_for(self, app, lock_attr):
        obj = app
        for part in lock_attr.split("."):
            obj = getattr(obj, part)
        return obj

    def _run_main_with_signal_mid_lock(self, wired, lock_attr, signum):
        """Simulate signal delivery while the main thread holds ``lock_attr``.

        main() is executed in a worker thread with a watchdog so a deadlock
        fails the test instead of hanging it.
        """
        app_holder = {}
        real_init = RadioApp.__init__

        def spy_init(self):
            real_init(self)
            app_holder["app"] = self

        def fake_run(*args):
            app = app_holder["app"]
            with self._lock_for(app, lock_attr):
                # Signal delivered between bytecodes while the lock is held.
                wired[signum](signum, None)  # raises SystemExit

        with patch.object(RadioApp, "__init__", spy_init), patch.object(RadioApp, "run", fake_run):
            outcome = {}

            def target():
                try:
                    main()
                    outcome["result"] = "returned"
                except SystemExit as exc:
                    outcome["result"] = f"exit:{exc.code}"
                except BaseException as exc:  # pragma: no cover - diagnostics only
                    outcome["result"] = f"error:{exc!r}"

            worker = threading.Thread(target=target, daemon=True)
            worker.start()
            worker.join(timeout=10)
            assert not worker.is_alive(), "deadlock: main() did not finish"
            return outcome["result"]

    def test_sigint_while_player_lock_held_completes_shutdown(self, wired):
        """Player._lock is held by play() around subprocess.Popen (issue #18)."""
        result = self._run_main_with_signal_mid_lock(wired, "_player._lock", signal.SIGINT)
        assert result == "exit:0"

    def test_sigterm_while_player_lock_held_completes_shutdown(self, wired):
        result = self._run_main_with_signal_mid_lock(wired, "_player._lock", signal.SIGTERM)
        assert result == "exit:0"

    def test_sigint_while_app_lock_held_completes_shutdown(self, wired):
        """RadioApp._lock is held in _start_load/_load_batch (issue #18)."""
        result = self._run_main_with_signal_mid_lock(wired, "_lock", signal.SIGINT)
        assert result == "exit:0"

    def test_shutdown_ran_after_interrupted_player_lock(self, wired):
        """The finally-cleanup actually ran: player stopped, loaders cleared."""
        app_state = {}

        def fake_run(*args):
            app = app_state["app"]
            with app._player._lock:
                wired[signal.SIGINT](signal.SIGINT, None)

        real_init = RadioApp.__init__

        def spy_init(self):
            real_init(self)
            app_state["app"] = self

        with patch.object(RadioApp, "__init__", spy_init), patch.object(RadioApp, "run", fake_run):
            started = time.monotonic()
            with pytest.raises(SystemExit):
                main()
            assert time.monotonic() - started < 10

        app = app_state["app"]
        assert app._player.is_playing() is False
        assert app._stations_loader is None
        assert app._loading is False
