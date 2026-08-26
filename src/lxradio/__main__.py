import contextlib
import locale
import logging
import signal

from .app import RadioApp


def _signal_handler(signum, frame):
    # Signal handlers run on the main thread between bytecodes, even while the
    # interrupted code holds a non-reentrant lock (Player._lock around the mpv
    # Popen, RadioApp._lock in load batches). Cleanup that acquires locks must
    # therefore never run here — it would self-deadlock (issue #18). Just
    # unwind; app.shutdown() runs from the finally below once any held locks
    # have been released by the exception propagation.
    raise SystemExit(0)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(levelname)s: %(message)s")
    with contextlib.suppress(locale.Error):
        # Required by the curses documentation for proper (wide-character)
        # Unicode handling; harmless if it fails (issue #16).
        locale.setlocale(locale.LC_ALL, "")
    app = RadioApp()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        app.run()
    finally:
        # Runs on the main thread after the interrupted frame unwound, so any
        # locks held at signal-delivery time have been released before
        # shutdown() re-acquires them. Also covers normal exit (shutdown is
        # idempotent).
        app.shutdown()


if __name__ == "__main__":
    main()
