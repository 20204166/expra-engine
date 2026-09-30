"""Toolkit-independent Normal Map Setup dialog logic.

The dialog owns presentation and user input only; all planning, generation,
file writing and undoable assignment flow through the shared owners
(``editor.normal_mapping_workflow``, ``editor.normal_map_generation`` and the
editor command stack). A frontend supplies the selection, generation settings
and the presentation hooks declared below.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

from expra_engine.editor.normal_map_generation import (
    NormalMapGenerationSettings,
    generate_normal_map_png,
    normal_map_output_id,
    write_generated_normal,
)
from expra_engine.editor.normal_mapping_workflow import (
    NormalMapAssetCandidate,
    NormalMapClassification,
    NormalMapSetupPlan,
    apply_normal_map_setup,
    build_normal_map_setup_plan,
)
from expra_engine.runtime.normal_mapping import NormalMapEncoding, NormalMapMode
from expra_engine.runtime.rendering import NormalMapDescriptor

__all__ = ("NormalMapSetupDialogCore",)


class NormalMapSetupDialogCore:
    """Shared logic behind the Qt Normal Map Setup dialog."""

    def _init_setup_state(
        self,
        window: Any,
        plan: NormalMapSetupPlan,
        project: Any,
        resources: Any,
    ) -> None:
        self._window = window
        self._plan = plan
        self._project = project
        self._resources = resources

    # -- frontend hooks -------------------------------------------------

    def _selected_base_ids(self) -> frozenset[str]:
        raise NotImplementedError

    def _generation_settings(self) -> NormalMapGenerationSettings:
        raise NotImplementedError

    def _refresh_rows(self) -> None:
        raise NotImplementedError

    def _show_preview(self, preview: Any, metadata: str) -> None:
        raise NotImplementedError

    def _destroy_dialog(self) -> None:
        raise NotImplementedError

    def _refresh_assets(self) -> None:
        raise NotImplementedError

    def _show_error(self, message: str) -> None:
        raise NotImplementedError

    # -- shared logic ----------------------------------------------------

    @property
    def plan(self) -> NormalMapSetupPlan:
        return self._plan

    def refresh_plan(self) -> None:
        self._plan = build_normal_map_setup_plan(self._plan.scene, self._resources)
        self._refresh_rows()

    def _albedo(self, base_texture_id: str) -> Image.Image:
        try:
            return Image.open(io.BytesIO(self._resources.read_bytes(base_texture_id)))
        except Exception as exc:
            raise ValueError(f"could not decode base texture {base_texture_id}") from exc

    def generate_selected(self) -> int:
        """Generate PNG normal maps for the selected CAN_GENERATE candidates."""
        settings = self._generation_settings()
        selected = self._selected_base_ids()
        generated = 0
        for base_id in sorted(selected):
            candidate = self._plan.candidates_by_id().get(base_id)
            if candidate is None or not candidate.generation_eligible:
                continue
            if candidate.classification is not NormalMapClassification.CAN_GENERATE:
                continue
            albedo = self._albedo(base_id)
            png = generate_normal_map_png(albedo, settings)
            write_generated_normal(self._project, base_id, png)
            generated += 1
        if generated:
            self._refresh_assets()
            self.refresh_plan()
        return generated

    def preview_selected(self) -> None:
        """Preview the first selected candidate in memory (no file is written)."""
        selected = sorted(self._selected_base_ids())
        if not selected:
            return
        base_id = selected[0]
        settings = self._generation_settings()
        albedo_image = self._albedo(base_id)
        png = generate_normal_map_png(albedo_image, settings)
        try:
            import pygame

            from expra_engine.ui.normal_map_preview import build_normal_map_preview
        except ImportError as exc:
            self._show_error(str(exc))
            return
        albedo_surface = pygame.image.load(io.BytesIO(self._resources.read_bytes(base_id)))
        normal_surface = pygame.image.load(io.BytesIO(png))
        descriptor = NormalMapDescriptor(
            mode=NormalMapMode.AUTO_PAIR,
            texture_id=str(normal_map_output_id(base_id)),
            strength=settings.strength,
            y_convention=settings.y_convention,
            encoding=NormalMapEncoding.RGB_XYZ,
        )
        preview = build_normal_map_preview(pygame, albedo_surface, normal_surface, descriptor)
        self._show_preview(
            preview,
            f"Preview (not saved yet): {normal_map_output_id(base_id)}\n"
            f"Preset: {settings.preset}  Strength: {settings.strength:g}  "
            f"Convention: {settings.y_convention}",
        )

    def apply_changes(self) -> bool:
        """Apply auto-pair material assignments for the selected candidates."""
        return apply_normal_map_setup(self._window, self._plan, self._selected_base_ids())

    def import_existing(self, base_texture_id: str) -> None:
        """Import an external normal-map file as the candidate's canonical pair."""
        dialogs = getattr(self._window, "_dialogs", None)
        if dialogs is None:
            raise RuntimeError("the editor window has no dialog provider")
        source = dialogs.ask_open_file(
            "Import Normal Map",
            filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg *.jpeg"), ("All files", "*.*")],
        )
        if not source:
            return
        output_id = normal_map_output_id(base_texture_id)
        try:
            self._project.import_asset(source, output_id.path)
        except Exception as exc:  # noqa: BLE001 - import failures are user-facing
            self._show_error(str(exc))
            return
        self._refresh_assets()
        self.refresh_plan()

    def close(self) -> None:
        self._destroy_dialog()


def candidate_action(candidate: NormalMapAssetCandidate) -> str:
    """Human-readable action label for a candidate row."""
    return {
        NormalMapClassification.READY_EXISTING: "Pair",
        NormalMapClassification.CAN_GENERATE: "Generate",
        NormalMapClassification.MISSING_MANUAL: "Import",
        NormalMapClassification.ALREADY_CONFIGURED: "Configured",
        NormalMapClassification.PRESERVED: "Preserved",
        NormalMapClassification.INVALID: "Invalid",
        NormalMapClassification.EXTERNAL_INSTANCE: "Open source scene",
        NormalMapClassification.NOT_APPLICABLE: "—",
    }[candidate.classification]
