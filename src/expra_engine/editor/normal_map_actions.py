"""Normal-map preview and auto-map actions contributed to the editor shell."""

from __future__ import annotations

from tkinter import messagebox

from expra_engine.core.scene import Scene
from expra_engine.editor.normal_mapping_workflow import (
    apply_level_auto_map,
    build_level_auto_map_plan,
)
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.normal_mapping import NormalMapResolver, normal_texture_sources
from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
from expra_engine.ui.normal_map_preview import build_normal_map_preview, show_normal_map_preview


class NormalMapEditorActionsMixin:
    """Normal-map authoring dialogs and preview presentation for EditorWindow."""

    def _on_normal_map_preview(self, entity_id: str, component_index: int) -> None:
        project = self._engine.project
        document = self._active_document.document
        if project is None or not isinstance(document, Scene):
            messagebox.showwarning(
                "Normal Map Preview", "Open a Scene or Level in a project first.", parent=self._root
            )
            return
        entity = document.find_entity(entity_id)
        if entity is None or not 0 <= component_index < len(entity.components):
            return
        material = entity.components[component_index]
        if not isinstance(material, MaterialComponent) or material.normal_map_descriptor is None:
            messagebox.showinfo(
                "Normal Map Preview",
                "Enable Explicit or Auto Pair normal mapping on this Material first.",
                parent=self._root,
            )
            return
        sources = normal_texture_sources(entity)
        if not sources:
            messagebox.showwarning(
                "Normal Map Preview",
                "This Entity has no textured Sprite or AnimatedSprite2D frame.",
                parent=self._root,
            )
            return
        base_texture_id = sources[0][1]
        resources = project.resource_service(observer=self._observer)
        resolver = NormalMapResolver(resources)
        resolution = resolver.inspect(
            base_texture_id,
            material.normal_map_mode,
            explicit_texture_id=material.normal_texture_id,
        )
        if resolution.normal_texture_id is None or resolution.status.value != "resolved":
            messagebox.showerror(
                "Normal Map Preview",
                resolution.detail or f"Normal map is {resolution.status.value}.",
                parent=self._root,
            )
            return
        try:
            import pygame

            provider = PygameResourceProvider(pygame, resources, observer=self._observer)
            albedo = provider(base_texture_id)
            normal = provider(resolution.normal_texture_id)
            if albedo is None or normal is None:
                raise ValueError("normal or albedo texture could not be decoded")
            preview = build_normal_map_preview(
                pygame,
                albedo,
                normal,
                material.normal_map_descriptor,
            )
            width, height = normal.get_size()
            show_normal_map_preview(
                self._root,
                preview,
                "\n".join(
                    (
                        f"Resource: {resolution.normal_texture_id}",
                        f"Resolution: {width} x {height} (8-bit backend channels)",
                        f"Convention: {material.normal_y_convention}",
                        f"Encoding: {material.normal_encoding}",
                        f"Strength: {material.normal_strength:g}",
                        f"Base source: {base_texture_id}",
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001 - preview failures stay editor-local
            messagebox.showerror("Normal Map Preview", str(exc), parent=self._root)

    def _on_normal_map_auto_map(self) -> None:
        project = self._engine.project
        document = self._active_document.document
        if project is None or not isinstance(document, Scene):
            messagebox.showwarning(
                "Auto-map Normal Textures",
                "Open a Scene or Level in a project first.",
                parent=self._root,
            )
            return
        try:
            plan = build_level_auto_map_plan(
                document,
                project.resource_service(observer=self._observer),
            )
        except Exception as exc:  # noqa: BLE001 - resource inspection is user-facing
            messagebox.showerror("Auto-map Normal Textures", str(exc), parent=self._root)
            return
        counts: dict[str, int] = {}
        for finding in plan.findings:
            counts[finding.state.value] = counts.get(finding.state.value, 0) + 1
        summary = "\n".join(
            f"{name.replace('_', ' ').title()}: {count}" for name, count in sorted(counts.items())
        ) or "No eligible textured visuals were found."
        details = "\n".join(
            f"{finding.entity_name} / {finding.visual_name}: {finding.state.value}"
            + (f" ({finding.detail})" if finding.detail else "")
            for finding in plan.findings[:40]
        )
        if details:
            summary = f"{summary}\n\n{details}"
            if len(plan.findings) > 40:
                summary += f"\n...and {len(plan.findings) - 40} more"
        if not plan.can_apply:
            messagebox.showinfo("Auto-map Normal Textures", summary, parent=self._root)
            return
        if messagebox.askyesno(
            "Auto-map Normal Textures",
            f"{summary}\n\nApply auto-pair mapping as one undoable edit?",
            parent=self._root,
        ):
            apply_level_auto_map(self, plan)
