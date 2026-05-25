import contextlib
import threading
from collections.abc import Callable


class SleepTimer:
    """Countdown timer that fades out mpv volume before expiry."""

    PRESETS = [15 * 60, 30 * 60, 60 * 60]
    FADE_DURATION = 60
    FADE_INTERVAL = 2

    def __init__(
        self,
        get_volume: Callable[[], int],
        set_volume: Callable[[int], None],
        on_expire: Callable[[], None],
    ) -> None:
        self._get_volume = get_volume
        self._set_volume = set_volume
        self._on_expire = on_expire
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._remaining: float = 0.0
        self._state: str = "idle"
        self._preset_index: int = -1

    def start(self, duration_sec: int) -> None:
        self.cancel()
        with self._lock:
            self._remaining = float(duration_sec)
            self._state = "running"
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None
        with self._lock:
            self._remaining = 0.0
            self._state = "idle"

    def remaining_seconds(self) -> float:
        with self._lock:
            return self._remaining

    def is_active(self) -> bool:
        with self._lock:
            return self._state in ("running", "fading")

    def is_fading(self) -> bool:
        with self._lock:
            return self._state == "fading"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def preset_index(self) -> int:
        return self._preset_index

    @preset_index.setter
    def preset_index(self, value: int) -> None:
        self._preset_index = value

    def cycle_preset(self) -> tuple[str, int] | None:
        n = len(self.PRESETS)
        self._preset_index = (self._preset_index + 1) % (n + 1)
        if self._preset_index >= n:
            return None
        duration = self.PRESETS[self._preset_index]
        return f"{duration // 60}m", duration

    def _run(self) -> None:
        fade_start_volume: int | None = None
        fade_start_remaining: float = 0.0
        last_step: int = 0

        while True:
            if self._stop_event.wait(timeout=1):
                return

            with self._lock:
                self._remaining -= 1
                if self._remaining <= self.FADE_DURATION and self._state == "running":
                    self._state = "fading"
                    fade_start_remaining = self._remaining
                    last_step = 0
                remaining = self._remaining
                state = self._state

            if state == "fading":
                if fade_start_volume is None:
                    fade_start_volume = self._get_volume()
                fade_elapsed = fade_start_remaining - remaining
                steps_so_far = int(fade_elapsed // self.FADE_INTERVAL)
                if steps_so_far > last_step:
                    last_step = steps_so_far
                    total_steps = max(fade_start_remaining / self.FADE_INTERVAL, 1)
                    progress = min(steps_so_far / total_steps, 1.0)
                    target = max(0, int(fade_start_volume * (1 - progress)))
                    with contextlib.suppress(OSError):
                        self._set_volume(target)

            if remaining <= 0:
                with self._lock:
                    self._state = "expired"
                    self._remaining = 0.0
                self._on_expire()
                with self._lock:
                    self._state = "idle"
                return
