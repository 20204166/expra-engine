"""Semantic document/resource kinds for the editor's persisted documents."""

from __future__ import annotations

from enum import StrEnum


class DocumentKind(StrEnum):
    """The canonical document kinds an Expra project stores.

    ``SCENE`` is a reusable composition; ``LEVEL`` is a playable spatial
    document that reuses the same entity graph and adds whole-level metadata.
    """

    SCENE = "scene"
    LEVEL = "level"
