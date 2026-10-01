"""Optional Pygame-to-native-image pixel bridge used by the editor viewport."""

from __future__ import annotations

import logging
import struct
import zlib
from collections.abc import Callable, Hashable, Mapping
from io import BytesIO
from typing import Any, cast

from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.normal_mapping import NormalMapResolver
from expra_engine.runtime.pygame_lighting import PygameLightingPass
from expra_engine.runtime.pygame_normal_mapping import PygameNormalMapCache
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider
from expra_engine.runtime.render_diagnostics import RenderDiagnostics
from expra_engine.runtime.rendering import (
    SUPPORTED_PRIMITIVE_KINDS,
    OrthographicCamera,
    RenderContext,
    RenderFrame,
    RenderItem,
    Viewport,
)

__all__ = (
    "EditorPixelRenderer",
    "encode_pygame_surface",
    "encode_pygame_surface_fast",
    "frame_textures_available",
    "render_editor_frame_to_image",
    "render_editor_frame_to_pixel_image",
)

_LOGGER = logging.getLogger(__name__)


def render_editor_frame_to_image(
    frame: RenderFrame,
    context: RenderContext,
    *,
    surface_factory: Callable[[tuple[int, int]], Any],
    renderer_factory: Callable[[Any], Any],
    encode_surface: Callable[[Any], bytes],
    image_factory: Callable[[bytes], Any],
    diagnostics: RenderDiagnostics | None = None,
    entity_names: Mapping[str, str] | None = None,
    observer: ObservabilityWatcher | None = None,
) -> Any | None:
    """Render one canonical frame and bridge its pixels into an editor image safely."""
    diagnostics = diagnostics or RenderDiagnostics(_LOGGER)
    try:
        surface = surface_factory((context.viewport.width, context.viewport.height))
        renderer = renderer_factory(surface)
        token = observer.begin("editor.pixelbridge.render") if observer is not None else None
        renderer.start(context)
        renderer.render(frame)
        if token is not None:
            assert observer is not None
            observer.finish(token)
        if getattr(renderer, "draw_failed", False):
            _log_presentation_failure(
                frame,
                "renderer produced an incomplete frame",
                diagnostics=diagnostics,
                entity_names=entity_names,
            )
            return None
        encode_token = observer.begin("editor.pixelbridge.encode") if observer is not None else None
        encoded = encode_surface(surface)
        if encode_token is not None:
            assert observer is not None
            observer.finish(encode_token)
        image_token = (
            observer.begin("editor.pixelbridge.photoimage") if observer is not None else None
        )
        image = image_factory(encoded)
        if image_token is not None:
            assert observer is not None
            observer.finish(image_token)
        diagnostics.clear()
        return image
    except Exception as exc:  # noqa: BLE001 - editor backend failures use geometry fallback
        _log_presentation_failure(
            frame,
            str(exc),
            diagnostics=diagnostics,
            entity_names=entity_names,
            failure_signature=type(exc).__name__,
        )
        return None


def encode_pygame_surface(pygame_module: Any, surface: Any) -> bytes:
    """Encode an offscreen surface as PNG bytes.

    Uses the backend's own (SDL_image) PNG encoder -- the general-purpose,
    always-correct path used by one-shot/offline consumers (the expra-mcp
    static runner's ``render_snapshot``) where per-frame latency doesn't
    matter. The live interactive editor viewport uses
    ``encode_pygame_surface_fast`` instead; see its docstring for why.
    """
    stream = BytesIO()
    pygame_module.image.save(surface, stream, "PNG")
    return stream.getvalue()


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def encode_pygame_surface_fast(pygame_module: Any, surface: Any) -> bytes:
    """Encode a surface as a real, valid, alpha-preserving PNG -- fast.

    No longer the live interactive editor viewport's path (see
    the Pillow bridge inside ``render_editor_frame_to_pixel_image``, which
    replaced it -- benchmarked ~4-7x faster end to end by skipping PNG
    encode/decode entirely). Kept as a tested, dependency-free (no Pillow
    needed), alpha-exact fast PNG encoder for offline consumers.

    Measured against Blacksite Relay at 1280x720 (60 render items) before
    the Pillow bridge existed: the backend's own PNG encoder
    (``encode_pygame_surface``) cost ~40-50ms per frame and decoding it back
    inside a toolkit image cost another ~20-35ms -- ~65-75ms total. Raw
    RGB/PPM was measured ~4x faster than this but was rejected: this editor
    renders onto a surface filled with (0, 0, 0, 0) precisely so the viewport
    canvas grid shows through empty regions (see
    ``PygameRenderer._clear_surface`` with ``clear_color=None``); PPM has no
    alpha channel and would replace that transparency with an opaque black
    rectangle -- a real visual regression.

    Instead this builds a minimal, spec-valid PNG (8-bit RGBA, filter type 0
    per scanline) using ``zlib`` level 1 ("fast") rather than SDL_image's
    default compression level -- ~3x faster end-to-end than the default path
    for typical editor scenes, because these scenes compress well (large
    flat/transparent regions).
    """
    width, height = surface.get_size()
    rgba = pygame_module.image.tostring(surface, "RGBA")
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # PNG filter type 0 (None) for this scanline
        raw += rgba[y * stride : (y + 1) * stride]
    compressed = zlib.compress(bytes(raw), level=1)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # color type 6 = truecolor+alpha
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _texture_id_for_item(item: RenderItem) -> str | None:
    texture_id = item.material.texture_id
    if texture_id is None and item.nine_slice is not None:
        texture_id = item.nine_slice.texture_id
    return texture_id


def frame_textures_available(
    frame: RenderFrame,
    context: RenderContext,
    resource_provider: Callable[[str], Any | None],
    *,
    diagnostics: RenderDiagnostics | None = None,
    entity_names: Mapping[str, str] | None = None,
    visible_items: tuple[RenderItem, ...] | None = None,
) -> bool:
    """Return whether every visible texture can participate in pixel rendering."""
    diagnostics = diagnostics or RenderDiagnostics(_LOGGER)
    try:
        items = frame.visible_items(context) if visible_items is None else visible_items
        if any(not isinstance(item, RenderItem) for item in items):
            raise TypeError("visible_items must contain RenderItem values")
        available = True
        for item in items:
            texture_id = _texture_id_for_item(item)
            if (
                texture_id is None
                and item.text is None
                and item.nine_slice is None
                and item.primitive.kind not in SUPPORTED_PRIMITIVE_KINDS
            ):
                diagnostics.report(
                    ("preflight", "primitive", item.key, item.primitive.kind),
                    "[Render] unsupported primitive: entity=%r id=%r kind=%r rotation=%.1f",
                    _entity_name(item.key, entity_names),
                    item.key,
                    item.primitive.kind,
                    item.world_transform.rotation,
                )
                available = False
                continue
            if texture_id is None:
                continue
            texture = resource_provider(texture_id)
            if texture is None:
                _log_texture_failure(
                    texture_id,
                    resource_provider,
                    diagnostics=diagnostics,
                    entity_id=item.key,
                    entity_names=entity_names,
                )
                available = False
                continue
            region = item.material.source_region
            if region is None:
                continue
            get_size = getattr(texture, "get_size", None)
            if not callable(get_size):
                continue
            width, height = cast(tuple[int, int], get_size())
            if (
                region.x < 0
                or region.y < 0
                or region.x + region.width > width
                or region.y + region.height > height
            ):
                diagnostics.report(
                    (
                        "preflight",
                        "source-region",
                        item.key,
                        texture_id,
                        region.x,
                        region.y,
                        region.width,
                        region.height,
                    ),
                    "[EditorTexture] invalid source region entity=%r id=%r resource=%s: %s",
                    _entity_name(item.key, entity_names),
                    item.key,
                    texture_id,
                    region,
                )
                available = False
        return available
    except Exception as exc:  # noqa: BLE001 - editor validation failures use geometry fallback
        _log_presentation_failure(
            frame,
            str(exc),
            diagnostics=diagnostics,
            entity_names=entity_names,
            failure_signature=type(exc).__name__,
        )
        return False


def _render_pillow_bridge(
    frame: RenderFrame,
    context: RenderContext,
    visible_items: tuple[RenderItem, ...],
    *,
    surface_factory: Callable[[tuple[int, int]], Any],
    renderer_factory: Callable[[Any], Any],
    pygame_module: Any,
    width: int,
    height: int,
    diagnostics: RenderDiagnostics,
    entity_names: Mapping[str, str] | None,
    observer: ObservabilityWatcher | None,
    photo_image_reuse: Any | None,
    image_factory: Callable[..., Any],
) -> Any | None:
    """Render one frame straight into an editor image via Pillow.

    Pygame surface -> ``pygame.image.tostring`` (RGBA bytes, no PNG) ->
    ``PIL.Image.frombuffer`` (zero-copy reinterpret of those same bytes) ->
    the image's ``paste`` (a direct in-memory pixel-block write into the
    existing image). No PNG compression, no PNG decode, and the live image
    object is reused across frames of the same size instead of reallocated.
    """
    total_token = observer.begin("editor.pixelbridge.total") if observer is not None else None
    try:
        surface = surface_factory((width, height))
        renderer = renderer_factory(surface)
        render_token = observer.begin("editor.pixelbridge.render") if observer is not None else None
        renderer.start(context)
        render_previsible = getattr(renderer, "render_previsible", None)
        if callable(render_previsible):
            render_previsible(frame, visible_items)
        else:
            renderer.render(frame)
        if render_token is not None:
            assert observer is not None
            observer.finish(render_token)
        if getattr(renderer, "draw_failed", False):
            _log_presentation_failure(
                frame,
                "renderer produced an incomplete frame",
                diagnostics=diagnostics,
                entity_names=entity_names,
            )
            return None
        extract_token = (
            observer.begin("editor.pixelbridge.extract") if observer is not None else None
        )
        rgba = pygame_module.image.tostring(surface, "RGBA")
        if extract_token is not None:
            assert observer is not None
            observer.finish(extract_token)
        encode_token = observer.begin("editor.pixelbridge.encode") if observer is not None else None
        from PIL import Image

        pil_image = Image.frombuffer("RGBA", (width, height), rgba, "raw", "RGBA", 0, 1)
        if encode_token is not None:
            assert observer is not None
            observer.finish(encode_token)
        upload_token = (
            observer.begin("editor.pixelbridge.photoimage") if observer is not None else None
        )
        if (
            photo_image_reuse is not None
            and photo_image_reuse.width() == width
            and photo_image_reuse.height() == height
        ):
            photo_image_reuse.paste(pil_image)
            image = photo_image_reuse
        else:
            image = image_factory(pil_image)
        if upload_token is not None:
            assert observer is not None
            observer.finish(upload_token)
        diagnostics.clear()
        return image
    except Exception as exc:  # noqa: BLE001 - editor backend failures use geometry fallback
        _log_presentation_failure(
            frame,
            str(exc),
            diagnostics=diagnostics,
            entity_names=entity_names,
            failure_signature=type(exc).__name__,
        )
        return None
    finally:
        if total_token is not None:
            assert observer is not None
            observer.finish(total_token)


def render_editor_frame_to_pixel_image(
    frame: RenderFrame,
    context: RenderContext,
    *,
    width: int,
    height: int,
    visible_items: tuple[RenderItem, ...] | None = None,
    resource_service: Any | None,
    resource_provider: Callable[[str], Any | None] | None,
    pygame_module: Any,
    image_factory: Callable[..., Any],
    diagnostics: RenderDiagnostics | None = None,
    entity_names: Mapping[str, str] | None = None,
    observer: ObservabilityWatcher | None = None,
    photo_image_reuse: Any | None = None,
    lighting_pass: PygameLightingPass | None = None,
    normal_map_resolver: NormalMapResolver | None = None,
    normal_map_cache: PygameNormalMapCache | None = None,
) -> Any | None:
    """Render a complete editor frame, or return ``None`` for geometry fallback.

    Uses a direct Pygame-surface -> Pillow -> editor-image pixel path (see
    ``_render_pillow_bridge``) rather than the PNG encode/decode round trip
    ``encode_pygame_surface``/``encode_pygame_surface_fast`` still provide
    for one-shot/offline consumers (e.g. the expra-mcp static
    ``render_snapshot`` runner, where a real PNG byte stream is the actual
    need, not a live editor image).
    """
    diagnostics = diagnostics or RenderDiagnostics(_LOGGER)
    visible_items = frame.visible_items(context) if visible_items is None else visible_items
    if any(not isinstance(item, RenderItem) for item in visible_items):
        raise TypeError("visible_items must contain RenderItem values")
    provider = resource_provider
    if provider is None:
        if any(_texture_id_for_item(item) is not None for item in visible_items):
            _log_presentation_failure(
                frame,
                "renderer has no resource provider",
                diagnostics=diagnostics,
                entity_names=entity_names,
            )
        return None
    if not frame_textures_available(
        frame,
        context,
        provider,
        diagnostics=diagnostics,
        entity_names=entity_names,
        visible_items=visible_items,
    ):
        return None
    try:
        font_init = getattr(getattr(pygame_module, "font", None), "init", None)
        if callable(font_init):
            font_init()
        image_init = getattr(getattr(pygame_module, "image", None), "init", None)
        if callable(image_init):
            image_init()
        flags = getattr(pygame_module, "SRCALPHA", 0)

        def surface_factory(size: tuple[int, int]) -> Any:
            return pygame_module.Surface(size, flags=flags)

        def renderer_factory(surface: Any) -> PygameRenderer:
            return PygameRenderer(
                pygame_module,
                surface,
                screen_size=(width, height),
                arena_bounds=(0, 0, width, height),
                resource_provider=provider,
                clear_color=None,
                diagnostics=diagnostics,
                observer=observer,
                lighting_pass=lighting_pass,
                normal_map_resolver=(
                    normal_map_resolver
                    if normal_map_resolver is not None
                    else NormalMapResolver(resource_service)
                    if resource_service is not None
                    else None
                ),
                normal_map_cache=normal_map_cache,
            )

        return _render_pillow_bridge(
            frame,
            context,
            visible_items,
            surface_factory=surface_factory,
            renderer_factory=renderer_factory,
            pygame_module=pygame_module,
            width=width,
            height=height,
            diagnostics=diagnostics,
            entity_names=entity_names,
            observer=observer,
            photo_image_reuse=photo_image_reuse,
            image_factory=image_factory,
        )
    except Exception as exc:  # noqa: BLE001 - editor backend failures use geometry fallback
        _log_presentation_failure(
            frame,
            str(exc),
            diagnostics=diagnostics,
            entity_names=entity_names,
            failure_signature=type(exc).__name__,
        )
        return None


def editor_render_context(editor_camera: Any, width: int, height: int) -> RenderContext:
    if isinstance(editor_camera, OrthographicCamera):
        return RenderContext(Viewport(0, 0, width, height), editor_camera)
    camera_width = editor_camera._camera.width
    camera_height = camera_width * height / width
    camera = OrthographicCamera(width=camera_width, height=camera_height)
    camera.position = editor_camera.position
    camera.rotation = editor_camera._camera.rotation
    return RenderContext(Viewport(0, 0, width, height), camera)


class EditorPixelRenderer:
    """Own optional Pygame resources and produce a complete editor image."""

    def __init__(
        self,
        resource_service: Any | None = None,
        *,
        observer: ObservabilityWatcher | None = None,
        image_factory: Callable[..., Any],
    ) -> None:
        self._resource_service = resource_service
        self._observer = observer
        self._image_factory = image_factory
        self._provider: PygameResourceProvider | None = None
        self._provider_resources: Any | None = None
        self._diagnostics = RenderDiagnostics(_LOGGER)
        self._last_image: Any | None = None
        # One image reused across frames via .paste() instead of allocating
        # a brand-new one every render. paste() does NOT resize in place (see
        # _render_pillow_bridge's width()/height() check), so a viewport
        # resize allocates a fresh image rather than reusing this one.
        self._photo_image: Any | None = None
        self._lighting_pass: PygameLightingPass | None = None
        self._normal_map_resolver: NormalMapResolver | None = (
            NormalMapResolver(resource_service) if resource_service is not None else None
        )
        self._normal_map_cache: PygameNormalMapCache | None = None

    @property
    def resource_service(self) -> Any | None:
        return self._resource_service

    @property
    def diagnostics(self) -> RenderDiagnostics:
        """Read-only access to the active failure signatures, if any.

        Lets a caller (e.g. an MCP tool) explain why ``render()`` last
        returned ``None`` -- Canvas fallback -- without re-parsing logs.
        """
        return self._diagnostics

    def set_resource_service(self, resource_service: Any | None) -> None:
        if resource_service is self._resource_service:
            return
        self._resource_service = resource_service
        self._provider = None
        self._provider_resources = None
        self._normal_map_resolver = (
            NormalMapResolver(resource_service) if resource_service is not None else None
        )
        if self._normal_map_cache is not None:
            self._normal_map_cache.clear()
        self._normal_map_cache = None
        self._diagnostics.clear()
        self._last_image = None
        self._photo_image = None
        if self._lighting_pass is not None:
            self._lighting_pass.clear()

    def clear(self) -> None:
        """Discard backend state and any image retained for failure recovery."""
        self._provider = None
        self._provider_resources = None
        if self._normal_map_resolver is not None:
            self._normal_map_resolver.clear()
        self._normal_map_resolver = None
        if self._normal_map_cache is not None:
            self._normal_map_cache.clear()
        self._normal_map_cache = None
        self._diagnostics.clear()
        self._last_image = None
        self._photo_image = None
        if self._lighting_pass is not None:
            self._lighting_pass.clear()

    def render(
        self,
        frame: RenderFrame,
        editor_camera: Any,
        width: int,
        height: int,
        *,
        entity_names: Mapping[str, str] | None = None,
        visible_items: tuple[RenderItem, ...] | None = None,
    ) -> Any | None:
        try:
            import pygame  # type: ignore[reportMissingImports]

            if self._lighting_pass is None or self._lighting_pass.pygame is not pygame:
                self._lighting_pass = PygameLightingPass(pygame)
            if self._normal_map_cache is None and any(
                item.material.normal_map is not None for item in frame.items
            ):
                self._normal_map_cache = PygameNormalMapCache(pygame)

            if (
                self._resource_service is not None
                and self._provider_resources is not self._resource_service
            ):
                self._provider = PygameResourceProvider(
                    pygame, self._resource_service, observer=self._observer
                )
                self._provider_resources = self._resource_service
            if self._resource_service is not None and self._normal_map_resolver is None:
                self._normal_map_resolver = NormalMapResolver(self._resource_service)
            image = render_editor_frame_to_pixel_image(
                frame,
                editor_render_context(editor_camera, width, height),
                width=width,
                height=height,
                visible_items=visible_items,
                resource_service=self._resource_service,
                resource_provider=self._provider,
                pygame_module=pygame,
                image_factory=self._image_factory,
                diagnostics=self._diagnostics,
                entity_names=entity_names,
                observer=self._observer,
                photo_image_reuse=self._photo_image,
                lighting_pass=self._lighting_pass,
                normal_map_resolver=self._normal_map_resolver,
                normal_map_cache=self._normal_map_cache,
            )
            if image is not None:
                self._last_image = image
                self._photo_image = image
                return image
            return self._last_image
        except Exception as exc:  # noqa: BLE001 - editor backend failures use geometry fallback
            _log_presentation_failure(
                frame,
                str(exc),
                diagnostics=self._diagnostics,
                entity_names=entity_names,
                failure_signature=type(exc).__name__,
            )
            return self._last_image


def _frame_texture_items(frame: RenderFrame) -> tuple[tuple[str, str], ...]:
    return tuple(
        dict.fromkeys(
            (item.key, texture_id)
            for item in frame.items
            for texture_id in (
                item.material.texture_id,
                item.nine_slice.texture_id if item.nine_slice is not None else None,
            )
            if texture_id is not None
        )
    )


def _entity_name(entity_id: str, entity_names: Mapping[str, str] | None) -> str:
    return entity_names.get(entity_id, entity_id) if entity_names is not None else entity_id


def _log_texture_failure(
    texture_id: str,
    resource_provider: Any,
    *,
    diagnostics: RenderDiagnostics,
    entity_id: str | None = None,
    entity_names: Mapping[str, str] | None = None,
) -> None:
    failure = getattr(resource_provider, "last_failure", None)
    stage = failure[0] if isinstance(failure, tuple) and failure else None
    if stage == "decode":
        detail = "unable to decode"
    elif stage in {"resolve", "read"}:
        detail = "unable to resolve"
    else:
        detail = "presentation failed"
    if entity_id is None:
        diagnostics.report(
            ("preflight", "texture", texture_id, stage or "unknown"),
            f"[EditorTexture] {detail} %s",
            texture_id,
        )
    else:
        diagnostics.report(
            ("preflight", "texture", entity_id, texture_id, stage or "unknown"),
            "[EditorTexture] %s entity=%r id=%r resource=%s",
            detail,
            _entity_name(entity_id, entity_names),
            entity_id,
            texture_id,
        )


def _log_presentation_failure(
    frame: RenderFrame,
    detail: str,
    *,
    diagnostics: RenderDiagnostics,
    entity_names: Mapping[str, str] | None = None,
    failure_signature: Hashable | None = None,
) -> None:
    if detail == "renderer has no resource provider":
        diagnostics.report(
            ("presentation", "no-resource-provider"),
            "[EditorTexture] renderer has no resource provider",
        )
        return
    signature = detail if failure_signature is None else failure_signature
    texture_items = _frame_texture_items(frame)
    if texture_items:
        for entity_id, texture_id in texture_items:
            diagnostics.report(
                ("presentation", entity_id, texture_id, signature),
                "[EditorTexture] presentation failed for entity=%r id=%r resource=%s: %s",
                _entity_name(entity_id, entity_names),
                entity_id,
                texture_id,
                detail,
            )
    elif frame.items:
        for item in frame.items:
            diagnostics.report(
                ("presentation", item.key, signature),
                "[EditorTexture] presentation failed for entity=%r id=%r: %s",
                _entity_name(item.key, entity_names),
                item.key,
                detail,
            )
    else:
        diagnostics.report(
            ("presentation", signature),
            "[EditorTexture] presentation failed: %s",
            detail,
        )
