"""Tests for the editor's optional canonical pixel-render bridge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from expra_engine.core.engine import EngineRunState
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.editor.contributions import EditorContext
from expra_engine.editor.preferences import EditorPreferences
from expra_engine.editor.project_workflow import ProjectWorkflow
from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    PrimitiveDescriptor,
    RenderContext,
    RenderFrame,
    RenderItem,
    Transform,
    Viewport,
)
from expra_engine.runtime.visual_components import SpriteComponent
from expra_engine.ui.editor_pixel_renderer import EditorPixelRenderer, frame_textures_available
from expra_engine.ui.editor_pixel_renderer import encode_pygame_surface as _encode_pygame_surface
from expra_engine.ui.editor_pixel_renderer import (
    render_editor_frame_to_image as _render_editor_frame_to_image,
)
from expra_engine.ui.viewport import (
    EditorRenderTarget,
    ViewportCamera,
    ViewportPanel,
    build_editor_render_target,
)


def test_editor_pixel_bridge_renders_and_encodes_the_canonical_frame() -> None:
    calls: list[tuple[str, object]] = []
    surface = object()

    class Renderer:
        def start(self, context: RenderContext) -> None:
            calls.append(("start", context))

        def render(self, frame: RenderFrame) -> None:
            calls.append(("render", frame))

    image = _render_editor_frame_to_image(
        RenderFrame(),
        RenderContext(Viewport(0, 0, 160, 90)),
        surface_factory=lambda size: calls.append(("surface", size)) or surface,
        renderer_factory=lambda value: calls.append(("renderer", value)) or Renderer(),
        encode_surface=lambda value: calls.append(("encode", value)) or b"png",
        image_factory=lambda value: calls.append(("image", value)) or SimpleNamespace(data=value),
    )

    assert image is not None
    assert image.data == b"png"
    assert [name for name, _ in calls] == [
        "surface",
        "renderer",
        "start",
        "render",
        "encode",
        "image",
    ]


def test_pygame_editor_encoder_requests_png_format() -> None:
    calls: list[object] = []

    class Image:
        def save(self, surface: object, stream: object, format_name: str) -> None:
            calls.extend((surface, stream, format_name))
            stream.write(b"png")  # type: ignore[union-attr]

    pygame = SimpleNamespace(image=Image())
    surface = object()

    assert _encode_pygame_surface(pygame, surface) == b"png"
    assert calls[0] is surface
    assert calls[2] == "PNG"


def test_editor_pixel_bridge_returns_none_for_backend_failures() -> None:
    image = _render_editor_frame_to_image(
        RenderFrame(),
        RenderContext(Viewport(0, 0, 160, 90)),
        surface_factory=lambda _size: (_ for _ in ()).throw(RuntimeError("no pygame")),
        renderer_factory=lambda _surface: object(),
        encode_surface=lambda _surface: b"png",
        image_factory=lambda value: value,
    )

    assert image is None


def test_editor_pixel_bridge_returns_none_for_incomplete_backend_frames() -> None:
    class Renderer:
        draw_failed = True

        def start(self, _context: RenderContext) -> None:
            return None

        def render(self, _frame: RenderFrame) -> None:
            return None

    image = _render_editor_frame_to_image(
        RenderFrame(),
        RenderContext(Viewport(0, 0, 160, 90)),
        surface_factory=lambda _size: object(),
        renderer_factory=lambda _surface: Renderer(),
        encode_surface=lambda _surface: b"png",
        image_factory=lambda value: value,
    )

    assert image is None


def test_editor_pixel_bridge_rejects_backend_without_draw_module() -> None:
    pygame = SimpleNamespace(font=SimpleNamespace(Font=lambda *_args: None))

    image = _render_editor_frame_to_image(
        RenderFrame(),
        RenderContext(Viewport(0, 0, 160, 90)),
        surface_factory=lambda _size: object(),
        renderer_factory=lambda surface: PygameRenderer(pygame, surface),
        encode_surface=lambda _surface: b"encoded-blank",
        image_factory=lambda value: value,
    )

    assert image is None


def test_missing_visible_texture_requires_tk_geometry_fallback() -> None:
    scene = Scene("missing texture")
    entity = scene.create_entity("ship", entity_id="ship")
    entity.add_component(SpriteComponent("assets://missing.png"))
    frame = extract_render_frame(scene)
    context = RenderContext(Viewport(0, 0, 160, 90))

    assert not frame_textures_available(frame, context, lambda _texture_id: None)


def test_unsupported_or_rotated_geometry_requires_tk_fallback() -> None:
    unsupported = RenderFrame(
        (
            RenderItem(
                "rounded",
                PrimitiveDescriptor("rounded_rectangle", (2.0, 1.0)),
                Transform(),
            ),
        )
    )
    rotated = RenderFrame(
        (
            RenderItem(
                "rotated",
                PrimitiveDescriptor("rectangle", (2.0, 1.0)),
                Transform(rotation=45.0),
            ),
        )
    )
    outlined_circle = RenderFrame(
        (
            RenderItem(
                "outlined",
                PrimitiveDescriptor("circle", (2.0, 2.0)),
                Transform(),
                material=SimpleNamespace(
                    texture_id=None,
                    outline=object(),
                    outline_width=1.0,
                ),
            ),
        )
    )
    missing_nine_slice = RenderFrame(
        (
            RenderItem(
                "panel",
                PrimitiveDescriptor("rectangle", (2.0, 1.0)),
                Transform(),
                nine_slice=SimpleNamespace(texture_id="assets://missing.png"),
            ),
        )
    )
    outlined_point = RenderFrame(
        (
            RenderItem(
                "point",
                PrimitiveDescriptor("point"),
                Transform(),
                material=SimpleNamespace(
                    texture_id=None,
                    outline=object(),
                    outline_width=1.0,
                ),
            ),
        )
    )
    context = RenderContext(Viewport(0, 0, 160, 90))

    assert not frame_textures_available(unsupported, context, lambda _texture_id: None)
    assert not frame_textures_available(rotated, context, lambda _texture_id: None)
    assert not frame_textures_available(outlined_circle, context, lambda _texture_id: None)
    assert not frame_textures_available(outlined_point, context, lambda _texture_id: None)
    assert not frame_textures_available(missing_nine_slice, context, lambda _texture_id: None)


def test_viewport_refreshes_target_after_camera_moves() -> None:
    scene = Scene("camera refresh")
    entity = scene.create_entity("ship", entity_id="ship")
    entity.add_component(SpriteComponent("assets://ship.png"))
    panel = ViewportPanel.__new__(ViewportPanel)
    panel._scene = scene
    panel._selected_id = None
    panel._camera = ViewportCamera((200, 100))
    panel._interpolator = None
    panel._interpolation_fraction = 0.0
    panel._animated_players = None
    panel._canvas = cast(Any, SimpleNamespace(winfo_width=lambda: 200, winfo_height=lambda: 100))
    panel._target = build_editor_render_target(scene, viewport=(200, 100), camera=panel._camera)
    panel._target_dirty = True
    panel._camera.pan(20.0, 0.0)

    panel._refresh_target_if_dirty()

    assert panel._target.items == ()


def test_sprite_offset_is_used_by_viewport_hit_testing() -> None:
    item = RenderItem(
        key="ship",
        primitive=PrimitiveDescriptor("sprite", (2.0, 2.0)),
        transform=Transform(),
        sprite_offset=(5.0, 0.0),
    )
    clicked: list[str | None] = []
    panel = ViewportPanel.__new__(ViewportPanel)
    panel._editor_overlays = True
    panel._canvas = cast(Any, SimpleNamespace(gettags=lambda _current: ()))
    panel._camera = ViewportCamera((400, 300))
    panel._target = EditorRenderTarget(RenderFrame((item,)), (item,), None)
    panel._on_entity_click = clicked.append
    x, y = panel._camera.project((5.0, 0.0))

    panel._on_click(SimpleNamespace(x=x, y=y))

    assert clicked == ["ship"]


def test_inspector_tuple_values_use_parser_friendly_text() -> None:
    from expra_engine.ui.inspector import InspectorPanel

    assert InspectorPanel.format_component_value((1.5, -2.0)) == "1.5, -2.0"


def test_viewport_resource_service_replacement_discards_decoded_provider() -> None:
    panel = ViewportPanel.__new__(ViewportPanel)
    old_service = object()
    new_service = object()
    panel._pixel_renderer = EditorPixelRenderer(old_service)
    panel._pixel_renderer._provider = object()  # type: ignore[assignment]
    panel._pixel_renderer._provider_resources = old_service

    panel.set_resource_service(new_service)

    assert panel._pixel_renderer.resource_service is new_service
    assert panel._pixel_renderer._provider is None
    assert panel._pixel_renderer._provider_resources is None


def test_open_project_replaces_viewport_resources(tmp_path: Path) -> None:
    project = Project.create("Pixel Game", tmp_path / "pixel-game")

    class Engine:
        project = None
        run_state = EngineRunState.EDIT

        def set_project(self, value: object) -> None:
            self.project = value

        def set_scene(self, _scene: object) -> None:
            return None

        def set_script_registry(self, _registry: object) -> None:
            return None

    class Viewport:
        def __init__(self) -> None:
            self.services: list[object | None] = []

        def set_resource_service(self, value: object | None) -> None:
            self.services.append(value)

    engine = Engine()
    viewport = Viewport()
    window = SimpleNamespace(
        _engine=engine,
        _viewport=viewport,
        _editor_context=EditorContext(engine, None, None),
        _command_stack=SimpleNamespace(clear=lambda: None, can_undo=False),
        _assets=SimpleNamespace(set_root_directory=lambda _path: None),
        _preferences=EditorPreferences(),
        _selected_id=None,
        _last_save_path=None,
        _root=SimpleNamespace(title=lambda _value: None),
        _actions=SimpleNamespace(set_enabled=lambda *_args: None),
        _console=SimpleNamespace(log=lambda *_args, **_kwargs: None),
        _update_project_actions=lambda: None,
        _present_all=lambda: None,
    )

    workflow = ProjectWorkflow(window)
    workflow.open_loaded(project)
    workflow.close_project()

    assert viewport.services[0] is not None
    assert viewport.services[-1] is None
