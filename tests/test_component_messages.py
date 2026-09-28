"""Component diagnostics have one canonical wording owner."""

from __future__ import annotations

import pytest

from expra_engine.core.component import component_from_dict
from expra_engine.core.component_schema import component_type_spec
from expra_engine.messages import component as component_messages


def test_unknown_component_type_message_preserves_repr_format() -> None:
    assert component_messages.unknown_component_type("missing") == (
        "Unknown component type: 'missing'"
    )


def test_component_deserialization_uses_canonical_unknown_type_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        component_messages, "unknown_component_type", lambda component_type: "canonical message"
    )
    with pytest.raises(ValueError) as exc_info:
        component_from_dict({"type": "missing"})
    assert str(exc_info.value) == "canonical message"


def test_component_schema_uses_canonical_unknown_type_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        component_messages, "unknown_component_type", lambda component_type: "canonical message"
    )
    with pytest.raises(KeyError) as exc_info:
        component_type_spec("missing")
    assert exc_info.value.args == ("canonical message",)
