"""EditorWindow surface for the canonical typed-document owner and its actions."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from expra_engine.core.document_kind import DocumentKind
from expra_engine.editor.commands import CommandStack

__all__ = ("EditorDocumentSurface",)


class EditorDocumentSurface:
    """Adapt the singular ActiveDocument owner into EditorWindow compatibility views.

    Owns the typed New/Save/Save-As/Duplicate action wrappers and the
    ``_selected_ids`` / ``_last_save_path`` / ``_command_stack`` aliases so
    existing editor callers keep working while document ownership stays single.
    Also carries the thin project-workflow action delegations that the menu
    contributions bind to.
    """

    def _act_new_project(self) -> None:
        self._project_workflow.new_project()

    def _act_open_project(self) -> None:
        self._project_workflow.open_project()

    def _act_open_project_manifest(self) -> None:
        self._project_workflow.open_project_manifest()

    def _act_import_asset(self) -> None:
        self._project_workflow.import_assets()

    def _act_configure_input(self) -> None:
        self._project_workflow.configure_input()

    def _act_close_project(self) -> None:
        self._project_workflow.close_project()

    def _open_loaded_project(self, project: object) -> None:
        self._project_workflow.open_loaded(project)

    def _recent_project_command(self, project: str) -> Callable[[], None]:
        return lambda: self._act_open_recent(project)

    def _act_open_recent(self, project: str) -> None:
        self._project_workflow.open_recent(project)

    @property
    def _selected_id(self) -> str | None:
        """Primary selected entity id, or None -- read-only alias for callers unaware of multi-select."""
        return self._selected_ids[0] if self._selected_ids else None

    @property
    def _selected_ids(self) -> tuple[str, ...]:
        return self._active_document.selection

    @_selected_ids.setter
    def _selected_ids(self, identifiers: tuple[str, ...]) -> None:
        self._active_document.select(tuple(identifiers))

    @property
    def _last_save_path(self) -> Path | None:
        """Compatibility view of the active document's canonical path."""
        return self._active_document.path

    @_last_save_path.setter
    def _last_save_path(self, path: Path | None) -> None:
        self._active_document.path = path

    @property
    def _command_stack(self) -> CommandStack:
        """Undo ownership follows the active authored document."""
        return self._active_document.command_stack

    def _act_new_scene(self) -> None:
        """Compatibility alias for callers that explicitly request a Scene."""
        default_name = "New Scene" if self._engine.project is None else None
        self._project_workflow.new_document(DocumentKind.SCENE, default_name)

    def _act_new_document(self) -> None:
        self._project_workflow.new_document(
            self._active_document.kind or DocumentKind.SCENE
        )

    def _act_create_typed_document(self, kind: DocumentKind | str) -> None:
        self._project_workflow.new_document(kind)

    def _act_new_world(self) -> None:
        self._project_workflow.new_document(DocumentKind.WORLD)

    def _act_new_level(self) -> None:
        self._project_workflow.new_document(DocumentKind.LEVEL)

    def _act_save_scene(self) -> None:
        """Compatibility alias for the single typed-document Save action."""
        self._act_save_document()

    def _act_save_document(self) -> None:
        self._project_workflow.save_active_document()

    def _act_save_document_as(self) -> None:
        self._project_workflow.save_active_document_as()

    def _act_duplicate_document(self, name: str | None = None) -> None:
        self._project_workflow.duplicate_document(name)

    def _act_save_scene_silent(self) -> None:
        workflow = getattr(self, "_project_workflow", None)
        if workflow is not None:
            workflow.save_scene_silent()
            return
        if (
            self._last_save_path is not None
            and self._engine.edit_scene is not None
            and self._engine.project is None
        ):
            self._last_save_path.write_text(
                json.dumps(self._engine.edit_scene.to_dict(), indent=2), encoding="utf-8"
            )

    def _save_label_for_kind(self) -> str:
        return {
            DocumentKind.SCENE: "Scene",
            DocumentKind.LEVEL: "Level",
            DocumentKind.WORLD: "World",
        }.get(self._active_document.kind, "Document")

    def _refresh_typed_save_labels(self) -> None:
        self._apply_save_label(self._save_label_for_kind())
