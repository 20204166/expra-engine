"""Normal-map preview and setup actions contributed to the editor shell."""

from __future__ import annotations

from typing import Any

from expra_engine.core.scene import Scene
from expra_engine.editor.normal_mapping_workflow import build_normal_map_setup_plan
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.normal_mapping import NormalMapResolver, normal_texture_sources
from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
from expra_engine.ui.normal_map_preview import build_normal_map_preview


class NormalMapEditorActionsMixin:
    """Normal-map authoring dialogs and preview presentation for EditorWindow."""

    # Provided by the concrete editor window.
    _engine: Any
    _active_document: Any
    _observer: Any
    _dialogs: Any
    _present_normal_map_preview: Any
    _open_normal_map_setup: Any

    def _on_normal_map_preview(self, entity_id: str, component_index: int) -> None:
        project = self._engine.project
        document = self._active_document.document
        if project is None or not isinstance(document, Scene):
            self._dialogs.show_warning(
                "Normal Map Preview", "Open a Scene or Level in a project first."
            )
            return
        entity = document.find_entity(entity_id)
        if entity is None or not 0 <= component_index < len(entity.components):
            return
        material = entity.components[component_index]
        if not isinstance(material, MaterialComponent) or material.normal_map_descriptor is None:
            self._dialogs.show_info(
                "Normal Map Preview",
                "Enable Explicit or Auto Pair normal mapping on this Material first.",
            )
            return
        sources = normal_texture_sources(entity)
        if not sources:
            self._dialogs.show_warning(
                "Normal Map Preview",
                "This Entity has no textured Sprite or AnimatedSprite2D frame.",
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
            self._dialogs.show_error(
                "Normal Map Preview",
                resolution.detail or f"Normal map is {resolution.status.value}.",
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
            self._present_normal_map_preview(
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
            self._dialogs.show_error("Normal Map Preview", str(exc))

    def _on_normal_map_auto_map(self) -> None:
        project = self._engine.project
        document = self._active_document.document
        if project is None or not isinstance(document, Scene):
            self._dialogs.show_warning(
                "Normal Map Setup",
                "Open a Scene or Level in a project first.",
            )
            return
        try:
            resources = project.resource_service(observer=self._observer)
            plan = build_normal_map_setup_plan(document, resources)
        except Exception as exc:  # noqa: BLE001 - resource inspection is user-facing
            self._dialogs.show_error("Normal Map Setup", str(exc))
            return
        self._open_normal_map_setup(plan, project, resources)
