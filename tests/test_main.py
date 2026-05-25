"""Tests for lxradio.__main__."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from lxradio.__main__ import main


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
    def test_signal_handler_calls_shutdown(self, mock_app_cls, mock_log, mock_signal):
        mock_app = MagicMock()
        mock_app_cls.return_value = mock_app
        main()
        # Extract the registered handler
        handler = mock_signal.call_args_list[0][0][1]
        with pytest.raises(SystemExit) as exc_info:
            handler(signal.SIGINT, None)
        assert exc_info.value.code == 0
        mock_app.shutdown.assert_called_once()

    @patch("lxradio.__main__.signal.signal")
    @patch("lxradio.__main__.logging.basicConfig")
    @patch("lxradio.__main__.RadioApp")
    def test_sigterm_handler_calls_shutdown(self, mock_app_cls, mock_log, mock_signal):
        mock_app = MagicMock()
        mock_app_cls.return_value = mock_app
        main()
        # Extract the SIGTERM handler
        handler = mock_signal.call_args_list[1][0][1]
        with pytest.raises(SystemExit) as exc_info:
            handler(signal.SIGTERM, None)
        assert exc_info.value.code == 0
        mock_app.shutdown.assert_called_once()
