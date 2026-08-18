"""Tests for lxradio.key_dispatcher."""

from unittest.mock import MagicMock

from lxradio.key_dispatcher import KeyBinding, KeyDispatcher


class TestKeyDispatcher:
    def _app(self):
        return MagicMock()

    def test_dispatch_unbound_returns_none(self):
        d = KeyDispatcher()
        assert d.dispatch(self._app(), ord("z")) is None

    def test_dispatch_registered(self):
        d = KeyDispatcher()
        handled = []
        d.register(KeyBinding((ord("x"),), lambda app: handled.append(1) or False, "x"))
        result = d.dispatch(self._app(), ord("x"))
        assert result is False
        assert len(handled) == 1

    def test_dispatch_tuple_key(self):
        d = KeyDispatcher()
        d.register(KeyBinding((ord("a"), ord("A")), lambda app: True, "a"))
        assert d.dispatch(self._app(), ord("A")) is True

    def test_dispatch_skips_when_predicate_false(self):
        d = KeyDispatcher()
        d.register(KeyBinding((ord("x"),), lambda app: True, "x", when=lambda app: False))
        assert d.dispatch(self._app(), ord("x")) is None

    def test_footer_includes_visible_excludes_hidden(self):
        d = KeyDispatcher()
        d.register(KeyBinding((ord("a"),), lambda app: False, "shown"))
        d.register(KeyBinding((ord("b"),), lambda app: False, "hidden", when=lambda app: False))
        d.register(KeyBinding((ord("c"),), lambda app: False, ""))
        text = d.footer_text(self._app())
        assert "shown" in text
        assert "hidden" not in text
