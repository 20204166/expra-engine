"""Structured diagnostics for project-owned texture assets."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import RenderContext, RenderFrame
from expra_engine.runtime.visual_components import SpriteComponent

__all__ = (
    "TextureDiagnosticReport",
    "TextureDiagnosticStage",
    "diagnose_texture",
)


@dataclass(frozen=True, slots=True)
class TextureDiagnosticStage:
    """One ordered, machine-readable diagnostic stage."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class TextureDiagnosticReport:
    """Immutable result of probing one logical texture asset."""

    asset_id: str
    entity_ids: tuple[str, ...] = ()
    stages: tuple[TextureDiagnosticStage, ...] = ()
    ok: bool = False
    failed_stage: str | None = None
    failure_detail: str | None = None
    mount: str | None = None
    physical_path: str | None = None
    byte_size: int | None = None
    texture_size: tuple[int, int] | None = None
    cache_key: str | None = None
    texture_type: str | None = None
    output_bounds: tuple[int, int, int, int] | None = None
    editor_image_size: tuple[int, int] | None = None


def diagnose_texture(
    project: Project,
    scene: Scene,
    asset_id: str,
    *,
    context: RenderContext,
    pygame_module: Any,
    image_master: Any | None = None,
) -> TextureDiagnosticReport:
    """Probe one static sprite asset through the existing render pipeline."""
    if not isinstance(project, Project):
        raise TypeError("project must be a Project")
    if not isinstance(scene, Scene):
        raise TypeError("scene must be a Scene")
    if not isinstance(context, RenderContext):
        raise TypeError("context must be a RenderContext")
    if pygame_module is None:
        raise TypeError("pygame_module must not be None")
    logical_id = str(ResourceId.parse(asset_id))
    entity_ids = tuple(
        entity.entity_id
        for entity in scene.entities
        if any(
            isinstance(component, SpriteComponent) and component.asset == logical_id
            for component in entity.components
            )
        )
    stages: list[TextureDiagnosticStage] = []
    if not entity_ids:
        return _failed_report(
            logical_id,
            entity_ids,
            stages,
            "sprite_component",
            "no SpriteComponent references the requested asset",
        )
    stages.append(
        TextureDiagnosticStage(
            "sprite_component", True, f"matched entities={','.join(entity_ids)}"
        )
    )

    try:
        extracted = extract_render_frame(scene)
    except Exception as exc:  # noqa: BLE001 - diagnostics convert pipeline failures to reports
        return _failed_report(logical_id, entity_ids, stages, "extract", str(exc))
    items = tuple(
        item
        for item in extracted.items
        if item.key in entity_ids and item.material.texture_id == logical_id
    )
    if not items:
        return _failed_report(
            logical_id,
            entity_ids,
            stages,
            "extract",
            "matching sprite did not produce a render item",
        )
    stages.append(TextureDiagnosticStage("extract", True, f"render items={len(items)}"))

    resources = project.resource_service()
    resource = ResourceId.parse(logical_id)
    try:
        handle = resources.resolver.resolve(resource)
    except Exception as exc:  # noqa: BLE001 - resolution failures are report data
        return _failed_report(logical_id, entity_ids, stages, "resolve", str(exc))
    metadata = handle.metadata
    physical_path = str(handle.physical_path) if handle.physical_path is not None else None
    stages.append(
        TextureDiagnosticStage(
            "resolve",
            True,
            f"mount={handle.mount}; physical_path={physical_path or '<archive>'}; "
            f"size={metadata.size}; sha256={metadata.content_hash}",
        )
    )
    try:
        data = resources.read_bytes(resource)
    except Exception as exc:  # noqa: BLE001 - byte-read failures are report data
        return _failed_report(
            logical_id,
            entity_ids,
            stages,
            "read",
            str(exc),
            mount=handle.mount,
            physical_path=physical_path,
        )
    stages.append(TextureDiagnosticStage("read", True, f"bytes={len(data)}"))

    return _probe_backend(
        logical_id,
        entity_ids,
        stages,
        items,
        context,
        pygame_module,
        resources,
        handle.mount,
        physical_path,
        len(data),
        image_master,
    )


def _probe_backend(
    asset_id: str,
    entity_ids: tuple[str, ...],
    stages: list[TextureDiagnosticStage],
    items: tuple[Any, ...],
    context: RenderContext,
    pygame_module: Any,
    resources: Any,
    mount: str,
    physical_path: str | None,
    byte_size: int,
    image_master: Any | None,
) -> TextureDiagnosticReport:
    for subsystem in ("font", "image"):
        initializer = getattr(getattr(pygame_module, subsystem, None), "init", None)
        if callable(initializer):
            initializer()
    provider = PygameResourceProvider(pygame_module, resources)
    texture = provider(asset_id)
    if texture is None:
        failure = provider.last_failure or ("decode", "provider returned no texture")
        return _failed_report(
            asset_id,
            entity_ids,
            stages,
            failure[0],
            failure[1],
            mount=mount,
            physical_path=physical_path,
            byte_size=byte_size,
            cache_key=asset_id,
        )
    texture_size = _texture_size(texture)
    if texture_size is None:
        return _failed_report(
            asset_id,
            entity_ids,
            stages,
            "decode",
            "decoded texture has no valid size",
            mount=mount,
            physical_path=physical_path,
            byte_size=byte_size,
            cache_key=asset_id,
            texture_type=_type_name(texture),
        )
    texture_type = _type_name(texture)
    stages.append(
        TextureDiagnosticStage(
            "decode",
            True,
            f"size={texture_size}; cache_key={asset_id}; type={texture_type}",
        )
    )

    surface_factory = getattr(pygame_module, "Surface", None)
    if not callable(surface_factory):
        return _failed_report(
            asset_id,
            entity_ids,
            stages,
            "render",
            "pygame module has no Surface factory",
            mount=mount,
            physical_path=physical_path,
            byte_size=byte_size,
            cache_key=asset_id,
            texture_size=texture_size,
            texture_type=texture_type,
        )
    try:
        surface = surface_factory(
            (context.viewport.width, context.viewport.height),
            flags=getattr(pygame_module, "SRCALPHA", 0),
        )
        renderer = PygameRenderer(
            pygame_module,
            surface,
            screen_size=(context.viewport.width, context.viewport.height),
            arena_bounds=(0, 0, context.viewport.width, context.viewport.height),
            resource_provider=provider,
            clear_color=None,
        )
        renderer.start(context)
        renderer.render(RenderFrame(items))
    except Exception as exc:  # noqa: BLE001 - backend failures become report data
        return _failed_report(
            asset_id,
            entity_ids,
            stages,
            "render",
            str(exc),
            mount=mount,
            physical_path=physical_path,
            byte_size=byte_size,
            cache_key=asset_id,
            texture_size=texture_size,
            texture_type=texture_type,
        )
    if renderer.draw_failed:
        return _failed_report(
            asset_id,
            entity_ids,
            stages,
            "render",
            "renderer reported an incomplete frame",
            mount=mount,
            physical_path=physical_path,
            byte_size=byte_size,
            cache_key=asset_id,
            texture_size=texture_size,
            texture_type=texture_type,
        )
    stages.append(TextureDiagnosticStage("render", True, "renderer completed"))
    output_bounds = _surface_bounds(surface)
    if output_bounds is None or output_bounds[2] <= 0 or output_bounds[3] <= 0:
        return _failed_report(
            asset_id,
            entity_ids,
            stages,
            "pixels",
            "rendered surface has no non-transparent pixels",
            mount=mount,
            physical_path=physical_path,
            byte_size=byte_size,
            cache_key=asset_id,
            texture_size=texture_size,
            texture_type=texture_type,
            output_bounds=output_bounds,
        )
    stages.append(TextureDiagnosticStage("pixels", True, f"bounds={output_bounds}"))
    return _editor_or_success(
        asset_id,
        entity_ids,
        stages,
        items,
        context,
        pygame_module,
        resources,
        provider,
        mount,
        physical_path,
        byte_size,
        texture_size,
        texture_type,
        output_bounds,
        image_master,
    )


def _editor_or_success(
    asset_id: str,
    entity_ids: tuple[str, ...],
    stages: list[TextureDiagnosticStage],
    items: tuple[Any, ...],
    context: RenderContext,
    pygame_module: Any,
    resources: Any,
    provider: PygameResourceProvider,
    mount: str,
    physical_path: str | None,
    byte_size: int,
    texture_size: tuple[int, int],
    texture_type: str,
    output_bounds: tuple[int, int, int, int],
    image_master: Any | None,
) -> TextureDiagnosticReport:
    editor_image_size: tuple[int, int] | None = None
    if image_master is not None:
        try:
            image = _render_editor_frame_to_tk_image(
                RenderFrame(items),
                context,
                width=context.viewport.width,
                height=context.viewport.height,
                resource_service=resources,
                resource_provider=provider,
                pygame_module=pygame_module,
                image_master=image_master,
            )
        except Exception as exc:  # noqa: BLE001 - presentation failures become report data
            image = None
            detail = str(exc)
        else:
            detail = "editor bridge returned no image"
        if image is None:
            return _failed_report(
                asset_id,
                entity_ids,
                stages,
                "editor_presentation",
                detail,
                mount=mount,
                physical_path=physical_path,
                byte_size=byte_size,
                cache_key=asset_id,
                texture_size=texture_size,
                texture_type=texture_type,
                output_bounds=output_bounds,
            )
        width = cast(Callable[[], Any] | None, getattr(image, "width", None))
        height = cast(Callable[[], Any] | None, getattr(image, "height", None))
        editor_image_size = (
            (int(width()), int(height())) if callable(width) and callable(height) else None
        )
        if editor_image_size is None:
            return _failed_report(
                asset_id,
                entity_ids,
                stages,
                "editor_presentation",
                "editor image has no width and height methods",
                mount=mount,
                physical_path=physical_path,
                byte_size=byte_size,
                cache_key=asset_id,
                texture_size=texture_size,
                texture_type=texture_type,
                output_bounds=output_bounds,
            )
        stages.append(TextureDiagnosticStage("editor_presentation", True, f"size={editor_image_size}"))
    return TextureDiagnosticReport(
        asset_id=asset_id,
        entity_ids=entity_ids,
        stages=tuple(stages),
        ok=True,
        mount=mount,
        physical_path=physical_path,
        byte_size=byte_size,
        texture_size=texture_size,
        cache_key=asset_id,
        texture_type=texture_type,
        output_bounds=output_bounds,
        editor_image_size=editor_image_size,
    )


def _texture_size(texture: Any) -> tuple[int, int] | None:
    get_size = getattr(texture, "get_size", None)
    if not callable(get_size):
        return None
    try:
        width, height = cast(tuple[int, int], get_size())
    except Exception:  # noqa: BLE001 - backend metadata is diagnostic input
        return None
    if int(width) <= 0 or int(height) <= 0:
        return None
    return int(width), int(height)


def _surface_bounds(surface: Any) -> tuple[int, int, int, int] | None:
    get_bounding_rect = getattr(surface, "get_bounding_rect", None)
    if not callable(get_bounding_rect):
        return None
    try:
        rect = cast(Any, get_bounding_rect())
        return int(rect.x), int(rect.y), int(rect.width), int(rect.height)
    except Exception:  # noqa: BLE001 - backend metadata is diagnostic input
        return None


def _type_name(value: Any) -> str:
    return type(value).__name__


def _render_editor_frame_to_tk_image(*args: Any, **kwargs: Any) -> Any:
    """Load the editor-only bridge without adding it to runtime exports."""
    module = importlib.import_module("expra_engine.ui.editor_pixel_renderer")
    return module.render_editor_frame_to_tk_image(*args, **kwargs)


def _failed_report(
    asset_id: str,
    entity_ids: tuple[str, ...],
    stages: list[TextureDiagnosticStage],
    stage: str,
    detail: str,
    *,
    mount: str | None = None,
    physical_path: str | None = None,
    byte_size: int | None = None,
    texture_size: tuple[int, int] | None = None,
    cache_key: str | None = None,
    texture_type: str | None = None,
    output_bounds: tuple[int, int, int, int] | None = None,
) -> TextureDiagnosticReport:
    return TextureDiagnosticReport(
        asset_id=asset_id,
        entity_ids=entity_ids,
        stages=(*stages, TextureDiagnosticStage(stage, False, detail)),
        failed_stage=stage,
        failure_detail=detail,
        mount=mount,
        physical_path=physical_path,
        byte_size=byte_size,
        texture_size=texture_size,
        cache_key=cache_key,
        texture_type=texture_type,
        output_bounds=output_bounds,
    )
