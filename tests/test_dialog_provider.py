"""Tests for the DialogProvider protocol and its Qt implementation.

Covers:
  - DialogProvider is a @runtime_checkable Protocol
  - QtDialogProvider satisfies the protocol
  - QtDialogProvider.__init__ stores parent; _p() resolves override-first
"""

from __future__ import annotations

from unittest.mock import MagicMock

from expra_engine.editor.dialog_provider import DialogProvider
from expra_engine.editor.qt.dialogs import QtDialogProvider


class TestDialogProviderProtocol:
    def test_qtdialog_satisfies_protocol(self) -> None:
        provider = QtDialogProvider()
        assert isinstance(provider, DialogProvider)

    def test_mock_does_not_satisfy_protocol(self) -> None:
        # A plain MagicMock without all methods is not a DialogProvider.
        mock = MagicMock(spec=[])
        assert not isinstance(mock, DialogProvider)


class TestQtDialogProviderInit:
    def test_stores_parent(self) -> None:
        sentinel = object()
        provider = QtDialogProvider(parent=sentinel)
        assert provider._parent is sentinel

    def test_default_parent_is_none(self) -> None:
        provider = QtDialogProvider()
        assert provider._parent is None

    def test_p_returns_override_when_provided(self) -> None:
        stored = object()
        override = object()
        provider = QtDialogProvider(parent=stored)
        assert provider._p(override) is override

    def test_p_returns_stored_when_no_override(self) -> None:
        stored = object()
        provider = QtDialogProvider(parent=stored)
        assert provider._p(None) is stored

    def test_p_returns_none_when_both_none(self) -> None:
        provider = QtDialogProvider()
        assert provider._p(None) is None


class TestQtFilterConversion:
    def test_empty_filetypes_gives_empty_string(self) -> None:
        from expra_engine.editor.qt.dialogs import _filetypes_to_qt_filter

        assert _filetypes_to_qt_filter([]) == ""

    def test_single_entry(self) -> None:
        from expra_engine.editor.qt.dialogs import _filetypes_to_qt_filter

        result = _filetypes_to_qt_filter([("Scene files", "*.scene.pb")])
        assert result == "Scene files (*.scene.pb)"

    def test_multiple_entries_joined_with_separator(self) -> None:
        from expra_engine.editor.qt.dialogs import _filetypes_to_qt_filter

        result = _filetypes_to_qt_filter(
            [("Scene files", "*.scene.pb"), ("All files", "*")]
        )
        assert result == "Scene files (*.scene.pb);;All files (*)"
