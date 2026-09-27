"""Single editor-owned identity for the currently authored document."""

from __future__ import annotations

from pathlib import Path

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene import Scene
from expra_engine.core.world import World
from expra_engine.editor.commands import CommandStack

EditorDocument = Scene | World


class ActiveDocument:
    """Own document identity, selection, undo history, and save dirtiness.

    Engine scene properties remain compatibility/runtime views. The editor's
    authored document, including a World with no editable Entity Scene, lives
    here as the canonical source for path, selection, and Play.
    """

    def __init__(self) -> None:
        self.document: EditorDocument | None = None
        self.path: Path | None = None
        self.selection: tuple[str, ...] = ()
        self.command_stack = CommandStack()
        self._explicit_dirty = False

    @property
    def kind(self) -> DocumentKind | None:
        document = self.document
        if document is None:
            return None
        return DocumentKind(document.document_kind)

    @property
    def play_source(self) -> EditorDocument | None:
        return self.document

    @property
    def is_dirty(self) -> bool:
        return self._explicit_dirty or self.command_stack.is_dirty

    def open(self, document: EditorDocument | None, path: Path | None = None) -> None:
        if document is not None and not isinstance(document, (Scene, World)):
            raise TypeError("active editor document must be a Scene, Level, or World")
        if path is not None and not isinstance(path, Path):
            raise TypeError("active editor document path must be a Path")
        self.document = document
        self.path = path
        self.selection = ()
        self._explicit_dirty = False
        self.command_stack.clear()

    def select(self, identifiers: tuple[str, ...]) -> None:
        if not isinstance(identifiers, tuple) or any(
            not isinstance(identifier, str) or not identifier for identifier in identifiers
        ):
            raise ValueError("document selection must contain non-empty string IDs")
        self.selection = tuple(dict.fromkeys(identifiers))

    def mark_dirty(self) -> None:
        self._explicit_dirty = True

    def mark_saved(self, path: Path | None = None) -> None:
        if path is not None:
            self.path = path
        self._explicit_dirty = False
        self.command_stack.mark_clean()


__all__ = ("ActiveDocument", "EditorDocument")
