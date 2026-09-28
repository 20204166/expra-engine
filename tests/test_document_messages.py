"""Repeated document-codec diagnostics have one wording owner."""

from __future__ import annotations

import importlib
import importlib.util


def test_document_messages_own_repeated_kind_and_world_parse_diagnostics() -> None:
    spec = importlib.util.find_spec("expra_engine.messages.document")
    assert spec is not None, "repeated document diagnostics have no canonical wording owner"
    messages = importlib.import_module("expra_engine.messages.document")

    assert messages.unsupported_document_kind("bundle") == "unsupported document kind: 'bundle'"
    assert messages.invalid_world_document("bad levels") == "invalid World document: bad levels"


def test_document_parse_diagnostic_bounds_nested_validation_text() -> None:
    spec = importlib.util.find_spec("expra_engine.messages.document")
    assert spec is not None
    messages = importlib.import_module("expra_engine.messages.document")

    message = messages.invalid_world_document("bad " * 10000)

    assert len(message) <= 550
    assert "..." in message
