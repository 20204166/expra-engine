"""Human-readable typed document codec diagnostics."""

from __future__ import annotations

from expra_engine.messages._format import bounded_repr, bounded_text


def unsupported_document_kind(kind: str) -> str:
    return f"unsupported document kind: {bounded_repr(kind)}"


def invalid_world_document(detail: str) -> str:
    return f"invalid World document: {bounded_text(detail, 512)}"


def invalid_document_value(detail: str) -> str:
    return f"document contains a non-finite or unrepresentable value: {bounded_text(detail, 512)}"


def document_int_out_of_range() -> str:
    return "document contains an integer outside the protobuf int64 range"
