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
from expra_engine.runtime.render_diagnostics import RenderDiagnostics
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    MaterialDescriptor,
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderFrame,
    RenderItem,
    Transform,
    Viewport,
)
from expra_engine.runtime.visual_components import PrimitiveComponent, SpriteComponent
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
from tests.support.texture_project import make_texture_project


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
    assert (
        "[EditorTexture] presentation failed: renderer produced an incomplete frame" in caplog.text
    )


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
    assert "[EditorTexture] renderer has no resource provider" in caplog.text


def test_editor_pixel_renderer_logs_presentation_failure(monkeypatch, caplog) -> None:
    renderer = EditorPixelRenderer(object())
    original_import = __import__

    def fail_pygame(name, *args, **kwargs):
        if name == "pygame":
            raise ModuleNotFoundError("No module named 'pygame'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_pygame)
    with caplog.at_level(logging.ERROR, logger="expra_engine.ui.editor_pixel_renderer"):
        image = renderer.render(RenderFrame(), ViewportCamera(), 160, 90, object())

    assert image is None
    assert "[EditorTexture] presentation failed" in caplog.text


def test_editor_renderer_deduplicates_failures_and_preserves_last_good_image(caplog) -> None:
    pytest.importorskip("pygame")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for editor presentation test")

    unsupported = RenderFrame(
        (
            RenderItem(
                "rounded",
                PrimitiveDescriptor("rounded_rectangle", (2.0, 1.0)),
                Transform(),
            ),
        )
    )
    different_unsupported = RenderFrame(
        (
            RenderItem(
                "hexagon",
                PrimitiveDescriptor("hexagon", (2.0, 1.0)),
                Transform(),
            ),
        )
    )
    renderer = EditorPixelRenderer(object())
    try:
        with caplog.at_level(logging.ERROR, logger="expra_engine.ui.editor_pixel_renderer"):
            for _ in range(100):
                assert (
                    renderer.render(
                        unsupported,
                        ViewportCamera(),
                        160,
                        90,
                        root,
                        entity_names={"rounded": "Unsupported Shape"},
                    )
                    is None
                )
            assert renderer.render(different_unsupported, ViewportCamera(), 160, 90, root) is None
            last_good = renderer.render(RenderFrame(), ViewportCamera(), 160, 90, root)
            assert last_good is not None
            assert (
                renderer.render(
                    unsupported,
                    ViewportCamera(),
                    160,
                    90,
                    root,
                    entity_names={"rounded": "Unsupported Shape"},
                )
                is last_good
            )

        messages = [record.getMessage() for record in caplog.records]
        unsupported_messages = [
            message for message in messages if "unsupported primitive" in message
        ]
        assert len(unsupported_messages) == 3
        assert "entity='Unsupported Shape'" in unsupported_messages[0]
    finally:
        root.destroy()


def test_editor_bridge_deduplicates_backend_failures_across_redraw_renderers(caplog) -> None:
    diagnostics = RenderDiagnostics(logging.getLogger("expra_engine.runtime.pygame_renderer"))

    class FailingSurface:
        def fill(self, _color: object) -> None:
            return None

        def blit(self, _texture: object, _destination: object) -> None:
            raise RuntimeError("blit failed")

    class Texture:
        def get_size(self) -> tuple[int, int]:
            return (16, 16)

    pygame = SimpleNamespace(draw=SimpleNamespace(), transform=SimpleNamespace())
    frame = RenderFrame(
        (
            RenderItem(
                "ship",
                PrimitiveDescriptor("sprite", (1.0, 1.0)),
                Transform(),
                material=MaterialDescriptor(texture_id="assets://ship.png"),
            ),
        )
    )

    with caplog.at_level(logging.ERROR, logger="expra_engine.runtime.pygame_renderer"):
        for _ in range(100):
            assert (
                _render_editor_frame_to_image(
                    frame,
                    RenderContext(Viewport(0, 0, 160, 90)),
                    surface_factory=lambda _size: FailingSurface(),
                    renderer_factory=lambda surface: PygameRenderer(
                        pygame,
                        surface,
                        resource_provider=lambda _texture_id: Texture(),
                        clear_color=None,
                        diagnostics=diagnostics,
                    ),
                    encode_surface=lambda _surface: b"unreachable",
                    image_factory=lambda value: value,
                    diagnostics=diagnostics,
                    entity_names={"ship": "Cargo Ship"},
                )
                is None
            )

    messages = [record.getMessage() for record in caplog.records]
    assert sum("[Render] draw failed for ship" in message for message in messages) == 1
    assert (
        sum(
            "entity='Cargo Ship'" in message and "renderer produced an incomplete frame" in message
            for message in messages
        )
        == 1
    )


def test_editor_bridge_deduplicates_changing_backend_error_details(caplog) -> None:
    diagnostics = RenderDiagnostics(logging.getLogger("expra_engine.ui.editor_pixel_renderer"))
    attempts = 0
    frame = RenderFrame(
        (
            RenderItem(
                "ship",
                PrimitiveDescriptor("sprite", (1.0, 1.0)),
                Transform(),
                material=MaterialDescriptor(texture_id="assets://ship.png"),
            ),
        )
    )

    def failing_surface(_size: tuple[int, int]) -> object:
        nonlocal attempts
        attempts += 1
        raise RuntimeError(f"surface failed {attempts}")

    with caplog.at_level(logging.ERROR, logger="expra_engine.ui.editor_pixel_renderer"):
        for _ in range(100):
            assert (
                _render_editor_frame_to_image(
                    frame,
                    RenderContext(Viewport(0, 0, 160, 90)),
                    surface_factory=failing_surface,
                    renderer_factory=lambda _surface: object(),
                    encode_surface=lambda _surface: b"unreachable",
                    image_factory=lambda value: value,
                    diagnostics=diagnostics,
                    entity_names={"ship": "Cargo Ship"},
                )
                is None
            )

    messages = [record.getMessage() for record in caplog.records]
    presentation_messages = [
        message for message in messages if "presentation failed for entity" in message
    ]
    assert len(presentation_messages) == 1


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


def test_final_editor_photoimage_preserves_nonuniform_png_pixels(tmp_path: Path) -> None:
    pygame = pytest.importorskip("pygame")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for real Tk editor presentation")

    project, scene, _asset_id = make_texture_project(tmp_path)
    rotated = scene.create_entity("rotated primitive", entity_id="rotated")
    rotated.add_component(TransformComponent(x=3.0, rotation=45.0))
    rotated.add_component(PrimitiveComponent(width=1.5, height=0.75, fill=(0.1, 0.8, 0.2, 1.0)))
    frame = extract_render_frame(scene)
    service = project.resource_service()
    pygame.init()
    try:
        provider = PygameResourceProvider(pygame, service)
        image = render_editor_frame_to_tk_image(
            frame,
            RenderContext(Viewport(0, 0, 160, 120)),
            width=160,
            height=120,
            resource_service=service,
            resource_provider=provider,
            pygame_module=pygame,
            image_master=root,
        )

        assert image is not None
        red, green, blue, yellow = (
            image.get(72, 54),
            image.get(88, 54),
            image.get(72, 66),
            image.get(88, 66),
        )
        assert red[0] > red[1] and red[0] > red[2]
        assert green[1] > green[0] and green[1] > green[2]
        assert blue[2] > blue[0] and blue[2] > blue[1]
        assert yellow[0] > yellow[2] and yellow[1] > yellow[2]
    finally:
        pygame.quit()
        root.destroy()


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
        assert (
            window._viewport._canvas.itemcget(window._viewport._pixel_image_item, "state")
            == "normal"
        )
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
        assert (
            window._viewport._canvas.itemcget(window._viewport._pixel_image_item, "state")
            == "normal"
        )
        runtime_scene = engine.active_scene
        assert runtime_scene is not None
        player = next(entity for entity in runtime_scene.entities if entity.name == "Operative")
        transform = player.get_component(TransformComponent)
        assert transform is not None
        before = (transform.x, transform.y)

        for name, keys, expected_rotation in (
            ("D", ("d",), 0.0),
            ("W", ("w",), 90.0),
            ("A", ("a",), 180.0),
            ("S", ("s",), -90.0),
            ("W+D", ("w", "d"), 45.0),
        ):
            for key in keys:
                for event in engine.input_map.press(PhysicalInput("keyboard", key)):
                    engine.signal(event)
            engine.tick(0.25)
            for key in keys:
                for event in engine.input_map.release(PhysicalInput("keyboard", key)):
                    engine.signal(event)
            window._present_all()
            for _ in range(5):
                window._root.update()

            aim = next(
                entity for entity in runtime_scene.entities if entity.name == "Aim Indicator"
            )
            aim_transform = aim.get_component(TransformComponent)
            assert aim_transform is not None
            assert aim_transform.rotation == pytest.approx(expected_rotation), name
            assert window._viewport._pixel_image is not None, name
            assert (
                window._viewport._canvas.itemcget(window._viewport._pixel_image_item, "state")
                == "normal"
            ), name

        assert (transform.x, transform.y) != before
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


def test_editor_preflight_matches_canonical_primitive_capabilities() -> None:
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
    assert frame_textures_available(rotated, context, lambda _texture_id: None)
    assert frame_textures_available(outlined_circle, context, lambda _texture_id: None)
    assert frame_textures_available(outlined_point, context, lambda _texture_id: None)
    assert not frame_textures_available(missing_nine_slice, context, lambda _texture_id: None)


def test_editor_preflight_reports_distinct_texture_failures_in_one_frame(caplog) -> None:
    frame = RenderFrame(
        (
            RenderItem(
                "first",
                PrimitiveDescriptor("sprite"),
                Transform(),
                material=SimpleNamespace(texture_id="assets://first.png", source_region=None),
            ),
            RenderItem(
                "second",
                PrimitiveDescriptor("sprite"),
                Transform(position=(1.0, 0.0, 0.0)),
                material=SimpleNamespace(texture_id="assets://second.png", source_region=None),
            ),
        )
    )

    with caplog.at_level(logging.ERROR, logger="expra_engine.ui.editor_pixel_renderer"):
        assert not frame_textures_available(
            frame,
            RenderContext(Viewport(0, 0, 160, 90)),
            lambda _: None,
            entity_names={"first": "First Ship", "second": "Second Ship"},
        )

    assert "assets://first.png" in caplog.text
    assert "assets://second.png" in caplog.text
    assert "entity='First Ship'" in caplog.text
    assert "entity='Second Ship'" in caplog.text


def test_editor_preflight_reports_invalid_regions_with_entity_context(caplog) -> None:
    frame = RenderFrame(
        (
            RenderItem(
                "atlas-sprite",
                PrimitiveDescriptor("sprite"),
                Transform(),
                material=SimpleNamespace(
                    texture_id="assets://atlas.png",
                    source_region=SimpleNamespace(x=4, y=4, width=8, height=8),
                ),
            ),
        )
    )

    class Texture:
        def get_size(self) -> tuple[int, int]:
            return (8, 8)

    with caplog.at_level(logging.ERROR, logger="expra_engine.ui.editor_pixel_renderer"):
        assert not frame_textures_available(
            frame,
            RenderContext(Viewport(0, 0, 160, 90)),
            lambda _texture_id: Texture(),
            entity_names={"atlas-sprite": "Atlas Sprite"},
        )

    assert "entity='Atlas Sprite'" in caplog.text
    assert "id='atlas-sprite'" in caplog.text
    assert "assets://atlas.png" in caplog.text


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
