"""Human-readable typed document codec diagnostics."""

from __future__ import annotations

from expra_engine.messages._format import bounded_repr, bounded_text


def unsupported_document_kind(kind: str) -> str:
    return f"unsupported document kind: {bounded_repr(kind)}"


def invalid_world_document(detail: str) -> str:
    return f"invalid World document: {bounded_text(detail, 512)}"
