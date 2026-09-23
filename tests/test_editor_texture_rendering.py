"""Tests for the editor's optional canonical pixel-render bridge."""

from __future__ import annotations

import logging
import tkinter as tk
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.editor.contributions import EditorContext
from expra_engine.editor.preferences import EditorPreferences
from expra_engine.editor.project_workflow import ProjectWorkflow
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.input import PhysicalInput
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderFrame,
    RenderItem,
    Transform,
    Viewport,
)
from expra_engine.runtime.visual_components import SpriteComponent
from expra_engine.ui.editor_pixel_renderer import (
    EditorPixelRenderer,
    frame_textures_available,
    render_editor_frame_to_tk_image,
)
from expra_engine.ui.editor_pixel_renderer import (
    encode_pygame_surface as _encode_pygame_surface,
)
from expra_engine.ui.editor_pixel_renderer import (
    render_editor_frame_to_image as _render_editor_frame_to_image,
)
from expra_engine.ui.editor_window import EditorWindow
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


def test_editor_pixel_bridge_returns_none_for_incomplete_backend_frames(caplog) -> None:
    class Renderer:
        draw_failed = True

        def start(self, _context: RenderContext) -> None:
            return None

        def render(self, _frame: RenderFrame) -> None:
            return None

    with caplog.at_level(logging.ERROR, logger="expra_engine.ui.editor_pixel_renderer"):
        image = _render_editor_frame_to_image(
            RenderFrame(),
            RenderContext(Viewport(0, 0, 160, 90)),
            surface_factory=lambda _size: object(),
            renderer_factory=lambda _surface: Renderer(),
            encode_surface=lambda _surface: b"png",
            image_factory=lambda value: value,
        )

    assert image is None
    assert "[Texture] Editor renderer reported an incomplete frame" in caplog.text


def test_editor_pixel_bridge_logs_missing_resource_provider(caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="expra_engine.ui.editor_pixel_renderer"):
        image = render_editor_frame_to_tk_image(
            RenderFrame(),
            RenderContext(Viewport(0, 0, 160, 90)),
            width=160,
            height=90,
            resource_service=object(),
            resource_provider=None,
            pygame_module=object(),
            image_master=object(),
        )

    assert image is None
    assert "[Texture] No resource provider attached to editor renderer" in caplog.text


def test_real_blacksite_png_reaches_editor_pixel_output() -> None:
    pygame = pytest.importorskip("pygame")
    project = Project.load(Path(__file__).parents[1] / "examples" / "blacksite_relay")
    scene = project.load_scene()
    entity = next(entity for entity in scene.entities if entity.name == "Operative")
    sprite = entity.get_component(SpriteComponent)
    assert sprite is not None
    asset = "assets://kenney/player_survivor_gun.png"
    assert sprite.asset == asset

    frame = extract_render_frame(scene)
    item = next(item for item in frame.items if item.key == entity.entity_id)
    assert item.material.texture_id == asset

    service = project.resource_service()
    handle = service.resolver.resolve(ResourceId.parse(asset))
    assert handle.physical_path == project.assets_dir / "kenney/player_survivor_gun.png"
    data = service.read_bytes(asset)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")

    pygame.init()
    try:
        provider = PygameResourceProvider(pygame, service)
        texture = provider(asset)
        assert texture is not None
        assert texture.get_size() == (51, 43)

        context = RenderContext(
            Viewport(0, 0, 320, 240),
            OrthographicCamera(width=88.0, height=66.0),
        )
        assert frame_textures_available(RenderFrame((item,)), context, provider)

        encoded = _render_editor_frame_to_image(
            RenderFrame((item,)),
            context,
            surface_factory=lambda size: pygame.Surface(size, flags=pygame.SRCALPHA),
            renderer_factory=lambda surface: PygameRenderer(
                pygame,
                surface,
                resource_provider=provider,
                clear_color=None,
            ),
            encode_surface=lambda surface: _save_pygame_png(pygame, surface),
            image_factory=lambda value: value,
        )

        assert encoded is not None
        decoded = pygame.image.load(BytesIO(encoded))
        assert decoded.get_bounding_rect().width > 0
        assert decoded.get_bounding_rect().height > 0
    finally:
        pygame.quit()


def test_blacksite_editor_edit_and_play_keep_real_pixels() -> None:
    pytest.importorskip("pygame")
    try:
        probe = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for real Tk editor test")
    probe.destroy()

    project = Project.load(Path(__file__).parents[1] / "examples" / "blacksite_relay")
    engine = Engine()
    window = EditorWindow(engine)
    try:
        window._project_workflow.open_loaded(project)
        window._viewport.frame_scene()
        for _ in range(5):
            window._root.update()

        assert engine.run_state is EngineRunState.EDIT
        assert window._viewport._pixel_image is not None
        assert window._viewport._canvas.itemcget(
            window._viewport._pixel_image_item, "state"
        ) == "normal"
        provider = window._viewport._pixel_renderer._provider
        assert provider is not None
        decoded_assets = set(provider._textures)
        assert {
            "assets://kenney/player_survivor_gun.png",
            "assets://kenney/survivor_blue.png",
            "assets://kenney/zombie.png",
        } <= decoded_assets

        assert engine.play()
        window._present_all()
        for _ in range(5):
            window._root.update()

        assert engine.run_state is EngineRunState.PLAY
        assert window._viewport._pixel_image is not None
        assert window._viewport._canvas.itemcget(
            window._viewport._pixel_image_item, "state"
        ) == "normal"
        runtime_scene = engine.active_scene
        assert runtime_scene is not None
        player = next(entity for entity in runtime_scene.entities if entity.name == "Operative")
        transform = player.get_component(TransformComponent)
        assert transform is not None
        before = (transform.x, transform.y)

        for event in engine.input_map.press(PhysicalInput("keyboard", "d")):
            engine.signal(event)
        engine.tick(0.25)
        for event in engine.input_map.release(PhysicalInput("keyboard", "d")):
            engine.signal(event)
        window._present_all()
        for _ in range(5):
            window._root.update()

        assert (transform.x, transform.y) != before
        assert window._viewport._pixel_image is not None
        assert window._viewport._canvas.itemcget(
            window._viewport._pixel_image_item, "state"
        ) == "normal"
    finally:
        if engine.run_state is not EngineRunState.EDIT:
            engine.stop()
        window._on_close()


def _save_pygame_png(pygame: Any, surface: Any) -> bytes:
    stream = BytesIO()
    pygame.image.save(surface, stream, "PNG")
    return stream.getvalue()


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
