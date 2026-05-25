import logging
import signal

from .app import RadioApp


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(levelname)s: %(message)s")
    app = RadioApp()

    def _signal_handler(signum, frame):
        app.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    app.run()


if __name__ == "__main__":
    main()
