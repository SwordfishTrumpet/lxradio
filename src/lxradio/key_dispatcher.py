"""Key dispatch for lxradio. Registration-driven input handling."""

from __future__ import annotations

import curses
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import RadioApp


@dataclass(frozen=True)
class KeyBinding:
    key: int | tuple[int, ...]
    handler: Callable[[RadioApp], bool | None]
    description: str
    when: Callable[[RadioApp], bool] = lambda app: True


class KeyDispatcher:
    """Maps key codes to handlers. Footer help is generated from the registry."""

    def __init__(self) -> None:
        self._bindings: list[KeyBinding] = []

    def register(self, binding: KeyBinding) -> None:
        self._bindings.append(binding)

    def dispatch(self, app: RadioApp, key: int) -> bool | None:
        """Return True for quit, False/None for continue."""
        for binding in self._bindings:
            if not binding.when(app):
                continue
            keys = binding.key if isinstance(binding.key, tuple) else (binding.key,)
            if key in keys:
                return binding.handler(app)
        return None

    def footer_text(self, app: RadioApp) -> str:
        parts: list[str] = []
        for binding in self._bindings:
            if binding.description and binding.when(app):
                parts.append(binding.description)
        return "  " + "   ".join(parts) + "  "


def _cycle_view(app: RadioApp) -> None:
    from .app import View  # lazy import to avoid circular dependency
    current = app._view
    if current == View.BROWSE:
        app._switch_view(View.FAVORITES)
    elif current == View.FAVORITES:
        app._switch_view(View.HISTORY)
    else:
        app._switch_view(View.BROWSE)


def make_default_dispatcher() -> KeyDispatcher:
    d = KeyDispatcher()
    d.register(KeyBinding((ord("q"), ord("Q")), lambda app: True, "q quit"))
    d.register(KeyBinding((curses.KEY_UP, ord("k")), lambda app: app._nav_up(), "↑↓ navigate"))
    d.register(KeyBinding((curses.KEY_DOWN, ord("j")), lambda app: app._nav_down(), ""))
    d.register(KeyBinding((curses.KEY_PPAGE,), lambda app: app._page_up(), ""))
    d.register(KeyBinding((curses.KEY_NPAGE,), lambda app: app._page_down(), ""))
    d.register(KeyBinding((curses.KEY_RESIZE,), lambda app: app._on_resize(), ""))
    d.register(KeyBinding((curses.KEY_ENTER, 10, 13), lambda app: app._enter(), "Enter play/mute"))
    d.register(KeyBinding((ord("f"), ord("F")), lambda app: app._toggle_favorite(), "F favourite"))
    d.register(KeyBinding((ord("\t"),), _cycle_view, "Tab view"))
    d.register(KeyBinding((ord("/"),), lambda app: app._start_search(), "/ search"))
    d.register(KeyBinding((ord("+"), ord("="), curses.KEY_RIGHT), lambda app: app._player.volume_up(), "←→ vol", when=lambda app: app._player.can_control_volume()))
    d.register(KeyBinding((ord("-"), curses.KEY_LEFT), lambda app: app._player.volume_down(), "", when=lambda app: app._player.can_control_volume()))
    d.register(KeyBinding((ord("m"), ord("M")), lambda app: app._toggle_mute(), "m mute", when=lambda app: app._player.can_control_volume()))
    d.register(KeyBinding((ord(" "),), lambda app: app._space(), ""))
    return d
