import threading
import time

import pytest

from lxradio.sleep_timer import SleepTimer


class FakeVolume:
    def __init__(self, initial: int = 80) -> None:
        self._volume = initial
        self.calls: list[int] = []

    def get(self) -> int:
        return self._volume

    def set(self, v: int) -> None:
        self._volume = v
        self.calls.append(v)


@pytest.fixture
def vol() -> FakeVolume:
    return FakeVolume()


@pytest.fixture
def expired() -> list[bool]:
    return [False]


def make_timer(vol: FakeVolume, expired: list[bool]) -> SleepTimer:
    def on_expire() -> None:
        expired[0] = True

    return SleepTimer(get_volume=vol.get, set_volume=vol.set, on_expire=on_expire)


def test_start_creates_thread_and_counts(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    assert not timer.is_active()
    assert timer.remaining_seconds() == 0.0

    timer.start(5)
    assert timer.is_active()
    assert timer.state == "running"

    time.sleep(2.5)
    assert timer.remaining_seconds() <= 3
    assert timer.remaining_seconds() > 0
    assert timer.is_active()

    timer.cancel()


def test_cancel_stops_thread(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(30)
    assert timer.is_active()

    timer.cancel()
    assert not timer.is_active()
    assert timer.remaining_seconds() == 0.0
    assert timer.state == "idle"
    assert not expired[0]


def test_state_transitions(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    assert timer.state == "idle"

    timer.start(90)
    assert timer.state == "running"
    assert not timer.is_fading()

    timer.cancel()
    assert timer.state == "idle"


def test_fade_reduces_volume(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(3)
    time.sleep(1.1)
    assert timer.state == "fading"

    time.sleep(4)
    assert timer.state == "idle"
    assert expired[0]
    assert len(vol.calls) > 0
    assert vol.calls[0] < vol.get() or vol.calls[0] == 0
    assert vol.calls[-1] == 0


def test_short_timer_enters_fading_immediately(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(2)
    time.sleep(1.1)
    assert timer.state == "fading"

    timer.cancel()


def test_cycle_preset(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)

    result = timer.cycle_preset()
    assert result == ("15m", 900)

    result = timer.cycle_preset()
    assert result == ("30m", 1800)

    result = timer.cycle_preset()
    assert result == ("60m", 3600)

    result = timer.cycle_preset()
    assert result is None

    result = timer.cycle_preset()
    assert result == ("15m", 900)


def test_start_cancels_existing(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(30)
    time.sleep(0.1)
    timer.start(15)
    time.sleep(0.1)

    assert timer.is_active()
    assert timer.remaining_seconds() <= 15

    timer.cancel()


def test_expire_calls_callback(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)
    timer.start(2)
    assert not expired[0]

    time.sleep(3)
    assert expired[0]
    assert timer.state == "idle"
    assert timer.remaining_seconds() == 0.0


def test_thread_safety_race(vol: FakeVolume, expired: list[bool]) -> None:
    timer = make_timer(vol, expired)

    def toggle() -> None:
        for _ in range(100):
            timer.start(1)
            time.sleep(0.01)
            timer.cancel()

    threads = [threading.Thread(target=toggle) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    timer.cancel()
    assert not expired[0]
