"""Optional Pygame-to-Tk pixel bridge used by the editor viewport."""

from __future__ import annotations

import logging
import struct
import zlib
from collections.abc import Callable, Hashable, Mapping
from io import BytesIO
from typing import Any, cast

from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider
from expra_engine.runtime.render_diagnostics import RenderDiagnostics
from expra_engine.runtime.rendering import OrthographicCamera, RenderContext, RenderFrame, Viewport

__all__ = (
    "EditorPixelRenderer",
    "PillowEditorPhotoImage",
    "encode_pygame_surface",
    "encode_pygame_surface_fast",
    "frame_textures_available",
    "render_editor_frame_to_image",
    "render_editor_frame_to_tk_image",
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
    """Render one canonical frame and bridge its pixels into Tk safely."""
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
        image_token = observer.begin("editor.pixelbridge.photoimage") if observer is not None else None
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
    """Encode an offscreen surface in a format Tk can decode.

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
    ``PillowEditorPhotoImage`` / the Pillow bridge inside
    ``render_editor_frame_to_tk_image``, which replaced it -- benchmarked
    ~4-7x faster end to end by skipping PNG encode/decode entirely). Kept as
    a tested, dependency-free (no Pillow needed), alpha-exact fast PNG
    encoder for any future non-Tk or offline consumer; also the reference
    this module's Pillow path was benchmarked against, see
    tools/perf/bench_pixel_bridge_candidates.py.

    Measured against Blacksite Relay at 1280x720 (60 render items) before
    the Pillow bridge existed: the backend's own PNG encoder
    (``encode_pygame_surface``) cost ~40-50ms per frame and decoding it back
    inside Tk's ``PhotoImage`` cost another ~20-35ms -- ~65-75ms total. Raw
    RGB/PPM was measured ~4x faster than this but was rejected: this editor
    renders onto a surface filled with (0, 0, 0, 0) precisely so the Tk
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


def frame_textures_available(
    frame: RenderFrame,
    context: RenderContext,
    resource_provider: Callable[[str], Any | None],
    *,
    diagnostics: RenderDiagnostics | None = None,
    entity_names: Mapping[str, str] | None = None,
) -> bool:
    """Return whether every visible texture can participate in pixel rendering."""
    diagnostics = diagnostics or RenderDiagnostics(_LOGGER)
    try:
        items = frame.visible_items(context)
        available = True
        for item in items:
            texture_id = item.material.texture_id
            if texture_id is None and item.nine_slice is not None:
                texture_id = item.nine_slice.texture_id
            if (
                texture_id is None
                and item.text is None
                and item.nine_slice is None
                and item.primitive.kind
                not in {"rectangle", "rect", "circle", "point", "rounded_rectangle"}
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


class PillowEditorPhotoImage:
    """A ``PIL.ImageTk.PhotoImage`` that also proxies real Tk pixel read-back.

    ``PIL.ImageTk.PhotoImage`` wraps a genuine ``tkinter.PhotoImage`` (usable
    anywhere Tk expects an image -- ``str(this)`` returns its real Tk image
    name) but does not expose ``tkinter.PhotoImage.get``/``transparency_get``
    itself. Those two methods are one-line forwards to the same underlying
    Tcl ``<image> get``/``<image> transparency get`` commands
    ``tkinter.PhotoImage`` calls, so proxying them here costs nothing and
    keeps pixel-level test/inspection code (and any future MCP pixel
    inspection) working exactly like it did against a plain
    ``tkinter.PhotoImage``.
    """

    def __init__(self, image: Any, *, master: Any) -> None:
        from PIL import ImageTk

        self._photo = ImageTk.PhotoImage(image, master=master)
        self.tk = self._photo.tk

    def __str__(self) -> str:
        return str(self._photo)

    def width(self) -> int:
        return self._photo.width()

    def height(self) -> int:
        return self._photo.height()

    def paste(self, image: Any) -> None:
        self._photo.paste(image)

    def get(self, x: int, y: int) -> tuple[int, int, int]:
        return self.tk.call(str(self), "get", x, y)

    def transparency_get(self, x: int, y: int) -> bool:
        return bool(self.tk.getboolean(self.tk.call(str(self), "transparency", "get", x, y)))

    def write(
        self,
        filename: str,
        format: str | None = None,  # matches tkinter.PhotoImage.write's own signature
        from_coords: tuple[int, ...] | None = None,
    ) -> None:
        """Match ``tkinter.PhotoImage.write`` -- used by expra-mcp's
        ``capture_viewport`` to export the live pixel layer as a PNG.
        """
        args: tuple[Any, ...] = (str(self), "write", filename)
        if format:
            args = (*args, "-format", format)
        if from_coords:
            args = (*args, "-from", *from_coords)
        self.tk.call(args)


def _render_pillow_bridge(
    frame: RenderFrame,
    context: RenderContext,
    *,
    surface_factory: Callable[[tuple[int, int]], Any],
    renderer_factory: Callable[[Any], Any],
    pygame_module: Any,
    width: int,
    height: int,
    image_master: Any,
    diagnostics: RenderDiagnostics,
    entity_names: Mapping[str, str] | None,
    observer: ObservabilityWatcher | None,
    photo_image_reuse: Any | None,
) -> Any | None:
    """Render one frame straight into a Tk photo image via Pillow.

    Pygame surface -> ``pygame.image.tostring`` (RGBA bytes, no PNG) ->
    ``PIL.Image.frombuffer`` (zero-copy reinterpret of those same bytes) ->
    ``PillowEditorPhotoImage.paste`` (a direct in-memory pixel-block write
    into the existing Tk photo image via Pillow's own maintained
    ``_imagingtk`` extension). No PNG compression, no PNG decode, and the
    live Tk image object is reused across frames of the same size instead of
    reallocated. Benchmarked ~4-7x faster end to end than the previous PNG
    bridge (``encode_pygame_surface_fast`` + ``tk.PhotoImage.configure``) on
    both Space Pong and Blacksite Relay at 800x600 and 1280x720 -- see
    tools/perf/bench_pixel_bridge_candidates.py.
    """
    total_token = observer.begin("editor.pixelbridge.total") if observer is not None else None
    try:
        surface = surface_factory((width, height))
        renderer = renderer_factory(surface)
        render_token = observer.begin("editor.pixelbridge.render") if observer is not None else None
        renderer.start(context)
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
        extract_token = observer.begin("editor.pixelbridge.extract") if observer is not None else None
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
        upload_token = observer.begin("editor.pixelbridge.photoimage") if observer is not None else None
        if (
            photo_image_reuse is not None
            and photo_image_reuse.width() == width
            and photo_image_reuse.height() == height
        ):
            photo_image_reuse.paste(pil_image)
            image = photo_image_reuse
        else:
            image = PillowEditorPhotoImage(pil_image, master=image_master)
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


def render_editor_frame_to_tk_image(
    frame: RenderFrame,
    context: RenderContext,
    *,
    width: int,
    height: int,
    resource_service: Any | None,
    resource_provider: PygameResourceProvider | None,
    pygame_module: Any,
    image_master: Any,
    diagnostics: RenderDiagnostics | None = None,
    entity_names: Mapping[str, str] | None = None,
    observer: ObservabilityWatcher | None = None,
    photo_image_reuse: Any | None = None,
) -> Any | None:
    """Render a complete editor frame, or return ``None`` for Tk fallback.

    Uses a direct Pygame-surface -> Pillow -> Tk pixel path (see
    ``_render_pillow_bridge``) rather than the PNG encode/decode round trip
    ``encode_pygame_surface``/``encode_pygame_surface_fast`` still provide
    for one-shot/offline consumers (e.g. the expra-mcp static
    ``render_snapshot`` runner, where a real PNG byte stream is the actual
    need, not a live Tk image).
    """
    diagnostics = diagnostics or RenderDiagnostics(_LOGGER)
    if resource_service is None:
        _log_presentation_failure(
            frame,
            "renderer has no resource provider",
            diagnostics=diagnostics,
            entity_names=entity_names,
        )
        return None
    if resource_provider is None:
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
        resource_provider,
        diagnostics=diagnostics,
        entity_names=entity_names,
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
                resource_provider=resource_provider,
                clear_color=None,
                diagnostics=diagnostics,
                observer=observer,
            )

        return _render_pillow_bridge(
            frame,
            context,
            surface_factory=surface_factory,
            renderer_factory=renderer_factory,
            pygame_module=pygame_module,
            width=width,
            height=height,
            image_master=image_master,
            diagnostics=diagnostics,
            entity_names=entity_names,
            observer=observer,
            photo_image_reuse=photo_image_reuse,
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
    camera_width = editor_camera._camera.width
    camera_height = camera_width * height / width
    camera = OrthographicCamera(width=camera_width, height=camera_height)
    camera.position = editor_camera.position
    camera.rotation = editor_camera._camera.rotation
    return RenderContext(Viewport(0, 0, width, height), camera)


class EditorPixelRenderer:
    """Own optional Pygame resources and produce a complete Tk image."""

    def __init__(
        self,
        resource_service: Any | None = None,
        *,
        observer: ObservabilityWatcher | None = None,
    ) -> None:
        self._resource_service = resource_service
        self._observer = observer
        self._provider: PygameResourceProvider | None = None
        self._provider_resources: Any | None = None
        self._diagnostics = RenderDiagnostics(_LOGGER)
        self._last_image: Any | None = None
        # One PillowEditorPhotoImage reused across frames via .paste()
        # instead of allocating+decoding a brand-new one every render.
        # Unlike tk.PhotoImage.configure(), Pillow's paste() does NOT resize
        # in place (see _render_pillow_bridge's width()/height() check), so
        # a viewport resize allocates a fresh image rather than reusing this
        # one. Also rebuilt whenever image_master changes, since a photo
        # image is bound to the Tk interpreter it was created under.
        self._photo_image: Any | None = None
        self._photo_image_master: Any | None = None

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
        self._diagnostics.clear()
        self._last_image = None
        self._photo_image = None
        self._photo_image_master = None

    def clear(self) -> None:
        """Discard backend state and any image retained for failure recovery."""
        self._provider = None
        self._provider_resources = None
        self._diagnostics.clear()
        self._last_image = None
        self._photo_image = None
        self._photo_image_master = None

    def render(
        self,
        frame: RenderFrame,
        editor_camera: Any,
        width: int,
        height: int,
        image_master: Any,
        *,
        entity_names: Mapping[str, str] | None = None,
    ) -> Any | None:
        if self._resource_service is None:
            _log_presentation_failure(
                frame,
                "renderer has no resource provider",
                diagnostics=self._diagnostics,
                entity_names=entity_names,
            )
            return None
        try:
            import pygame  # type: ignore[reportMissingImports]

            if self._provider_resources is not self._resource_service:
                self._provider = PygameResourceProvider(
                    pygame, self._resource_service, observer=self._observer
                )
                self._provider_resources = self._resource_service
            if self._photo_image_master is not image_master:
                self._photo_image = None
                self._photo_image_master = image_master
            image = render_editor_frame_to_tk_image(
                frame,
                editor_render_context(editor_camera, width, height),
                width=width,
                height=height,
                resource_service=self._resource_service,
                resource_provider=self._provider,
                pygame_module=pygame,
                image_master=image_master,
                diagnostics=self._diagnostics,
                entity_names=entity_names,
                observer=self._observer,
                photo_image_reuse=self._photo_image,
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
