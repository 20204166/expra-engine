"""Tests for core/errors.py — engine error types."""

import unittest

from expra_engine.core.errors import (
    BadChildException,
    BadEventHandlerException,
    NotMyChildError,
)


class _FakeEvent:
    pass


class _FakeUpdateEvent:
    pass


class _AoeEvent:  # starts with vowel
    pass


class _FakeOwner:
    pass


class TestBadEventHandlerException(unittest.TestCase):
    def test_is_type_error(self) -> None:
        exc = BadEventHandlerException(_FakeOwner(), "on_fake", _FakeEvent())
        self.assertIsInstance(exc, TypeError)

    def test_message_contains_handler_name(self) -> None:
        exc = BadEventHandlerException(_FakeOwner(), "on_update", _FakeUpdateEvent())
        self.assertIn("on_update", str(exc))

    def test_message_contains_event_type(self) -> None:
        exc = BadEventHandlerException(_FakeOwner(), "on_update", _FakeUpdateEvent())
        self.assertIn("FakeUpdateEvent", str(exc))

    def test_message_contains_owner_class(self) -> None:
        exc = BadEventHandlerException(_FakeOwner(), "on_update", _FakeUpdateEvent())
        self.assertIn("FakeOwner", str(exc))

    def test_vowel_article(self) -> None:
        exc = BadEventHandlerException(_FakeOwner(), "on_aoe", _AoeEvent())
        self.assertIn("an", str(exc))

    def test_consonant_article(self) -> None:
        exc = BadEventHandlerException(_FakeOwner(), "on_fake", _FakeEvent())
        self.assertIn("a", str(exc))


class TestBadChildException(unittest.TestCase):
    def test_is_exception(self) -> None:
        exc = BadChildException(int)
        self.assertIsInstance(exc, Exception)

    def test_message_contains_type_name(self) -> None:
        exc = BadChildException(int)
        self.assertIn("int", str(exc))


class TestNotMyChildError(unittest.TestCase):
    def test_is_exception(self) -> None:
        exc = NotMyChildError("not a child")
        self.assertIsInstance(exc, Exception)


if __name__ == "__main__":
    unittest.main()
