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
from expra_engine.observability import ObservabilityWatcher
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
    PillowEditorPhotoImage,
    frame_textures_available,
    render_editor_frame_to_tk_image,
)
from expra_engine.ui.editor_pixel_renderer import (
    encode_pygame_surface as _encode_pygame_surface,
)
from expra_engine.ui.editor_pixel_renderer import (
    encode_pygame_surface_fast as _encode_pygame_surface_fast,
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
                "triangle",
                PrimitiveDescriptor("triangle", (2.0, 1.0)),
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
                        entity_names={"triangle": "Unsupported Shape"},
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
                    entity_names={"triangle": "Unsupported Shape"},
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


def test_final_editor_photoimage_preserves_nonuniform_pixels(tmp_path: Path) -> None:
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
                "hexagon",
                PrimitiveDescriptor("hexagon", (2.0, 1.0)),
                Transform(),
            ),
        )
    )
    rounded_rectangle = RenderFrame(
        (
            RenderItem(
                "rounded",
                PrimitiveDescriptor("rounded_rectangle", (2.0, 1.0), 0.3),
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
    assert frame_textures_available(rounded_rectangle, context, lambda _texture_id: None)
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
    panel._editor_overlays = True
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


def test_encode_pygame_surface_fast_preserves_alpha_and_matches_pixels() -> None:
    """The fast editor encoder must round-trip real per-pixel alpha exactly.

    Raw RGB/PPM was rejected as a faster alternative specifically because it
    cannot represent this -- see encode_pygame_surface_fast's docstring.
    """
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        surface = pygame.Surface((4, 4), flags=pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))  # fully transparent, as the live editor renders
        surface.set_at((0, 0), (255, 0, 0, 255))  # opaque red
        surface.set_at((1, 0), (0, 0, 255, 128))  # semi-transparent blue
        surface.set_at((2, 0), (0, 0, 0, 0))  # explicit transparent

        png_bytes = _encode_pygame_surface_fast(pygame, surface)
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

        decoded = pygame.image.load(BytesIO(png_bytes))
        assert decoded.get_size() == (4, 4)
        assert tuple(decoded.get_at((0, 0))) == (255, 0, 0, 255)
        assert tuple(decoded.get_at((1, 0))) == (0, 0, 255, 128)
        assert tuple(decoded.get_at((2, 0))) == (0, 0, 0, 0)
        assert tuple(decoded.get_at((3, 3))) == (0, 0, 0, 0)
    finally:
        pygame.quit()


def test_editor_pixel_renderer_reuses_photoimage_across_frames(tmp_path: Path) -> None:
    """Section 4/5 fix: the same Tk PhotoImage object is configured in place
    across frames instead of a fresh one being allocated+decoded every call,
    but a change of Tk master (a different window) or an explicit clear()
    still produces a fresh image rather than reusing across an invalid scope.
    """
    pytest.importorskip("pygame")
    try:
        root_a = tk.Tk()
        root_b = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for real Tk editor presentation")

    try:
        project, scene, _asset_id = make_texture_project(tmp_path)
        frame = extract_render_frame(scene)
        renderer = EditorPixelRenderer(project.resource_service())
        camera = SimpleNamespace(
            position=(0.0, 0.0), _camera=SimpleNamespace(width=10.0, rotation=0.0)
        )

        first = renderer.render(frame, camera, 160, 120, root_a)
        second = renderer.render(frame, camera, 160, 120, root_a)
        assert first is not None
        assert second is first, "expected the same PhotoImage to be reconfigured, not recreated"

        different_master = renderer.render(frame, camera, 160, 120, root_b)
        assert different_master is not first, "a different Tk master must not reuse the old photo"

        renderer.clear()
        after_clear = renderer.render(frame, camera, 160, 120, root_b)
        assert after_clear is not different_master, "clear() must discard the reused photo image"
    finally:
        root_a.destroy()
        root_b.destroy()


def test_editor_pixel_renderer_records_pixelbridge_observability_stages(tmp_path: Path) -> None:
    """Wires the same ObservabilityWatcher UICoordinator already uses (see
    editor_window.EditorWindow._observer) so pixel-bridge stage timing shows
    up alongside ui:render:* commit timing in one unified snapshot -- the
    permanent regression-timing surface this smoothness pass was asked for.
    """
    pytest.importorskip("pygame")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for real Tk editor presentation")

    try:
        project, scene, _asset_id = make_texture_project(tmp_path)
        frame = extract_render_frame(scene)
        observer = ObservabilityWatcher()
        renderer = EditorPixelRenderer(project.resource_service(), observer=observer)
        camera = SimpleNamespace(
            position=(0.0, 0.0), _camera=SimpleNamespace(width=10.0, rotation=0.0)
        )

        image = renderer.render(frame, camera, 160, 120, root)
        assert image is not None

        snapshot = observer.snapshot()
        targets = {m.target: m for m in snapshot.metrics}
        for stage in (
            "editor.pixelbridge.render",
            "editor.pixelbridge.extract",
            "editor.pixelbridge.encode",
            "editor.pixelbridge.photoimage",
            "editor.pixelbridge.total",
        ):
            assert stage in targets, f"missing observability stage: {stage}"
            assert targets[stage].count == 1
            assert targets[stage].successes == 1
    finally:
        root.destroy()


def test_pillow_bridge_preserves_alpha_exactly(tmp_path: Path) -> None:
    """Chain-of-custody proof for the Pillow/ImageTk bridge that replaced the
    PNG bridge as the live interactive path (see
    ``editor_pixel_renderer._render_pillow_bridge``): five swatches --
    transparent, 25/50/75% alpha, and opaque, each a distinct RGB -- must
    survive pygame Surface -> tostring -> PIL.Image.frombuffer ->
    PillowEditorPhotoImage.paste() with zero loss, exactly like the PNG
    bridge it replaced (see
    test_encode_pygame_surface_fast_preserves_alpha_and_matches_pixels).
    """
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        root = tk.Tk()
    except tk.TclError:
        pygame.quit()
        pytest.skip("no display for real Tk editor presentation")

    try:
        swatches = {
            (0, 0): (255, 0, 0, 0),  # fully transparent
            (1, 0): (0, 255, 0, 64),  # 25% alpha
            (2, 0): (0, 0, 255, 128),  # 50% alpha
            (3, 0): (255, 255, 0, 191),  # 75% alpha
            (0, 1): (255, 0, 255, 255),  # fully opaque
        }
        surface = pygame.Surface((4, 4), flags=pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        for (x, y), rgba in swatches.items():
            surface.set_at((x, y), rgba)

        # 1. pygame's own extraction is lossless.
        rgba_bytes = pygame.image.tostring(surface, "RGBA")
        assert len(rgba_bytes) == 4 * 4 * 4
        for (x, y), expected in swatches.items():
            offset = (y * 4 + x) * 4
            assert tuple(rgba_bytes[offset : offset + 4]) == expected

        # 2. Pillow's raw decoder is a lossless reinterpret of those same bytes.
        from PIL import Image

        pil_image = Image.frombuffer("RGBA", (4, 4), rgba_bytes, "raw", "RGBA", 0, 1)
        for (x, y), expected in swatches.items():
            assert pil_image.getpixel((x, y)) == expected

        # 3. PillowEditorPhotoImage.paste() writes the same pixels into a
        #    real Tk photo image -- verify RGB via Tk's own .get() and the
        #    fully-transparent swatch via Tk's own .transparency_get(),
        #    the same two real-pixel-readback signals the previous PNG
        #    bridge's regression test used.
        photo = PillowEditorPhotoImage(pil_image, master=root)
        assert photo.transparency_get(0, 0) is True
        assert photo.transparency_get(0, 1) is False
        for (x, y), expected in swatches.items():
            if expected[3] == 0:
                continue  # Tk .get() RGB is undefined for a fully transparent pixel
            assert tuple(photo.get(x, y)) == expected[:3]
    finally:
        pygame.quit()
        root.destroy()


def test_pillow_bridge_reallocates_photoimage_on_resize(tmp_path: Path) -> None:
    """paste() does not resize in place (unlike tk.PhotoImage.configure()),
    so a viewport resize must allocate a fresh PillowEditorPhotoImage rather
    than corrupt/truncate the reused one -- see PATCH spec section 9/13.
    """
    pygame = pytest.importorskip("pygame")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for real Tk editor presentation")

    try:
        project, scene, _asset_id = make_texture_project(tmp_path)
        frame = extract_render_frame(scene)
        renderer = EditorPixelRenderer(project.resource_service())
        camera = SimpleNamespace(
            position=(0.0, 0.0), _camera=SimpleNamespace(width=10.0, rotation=0.0)
        )

        small = renderer.render(frame, camera, 160, 120, root)
        assert small is not None
        assert (small.width(), small.height()) == (160, 120)

        same_size_again = renderer.render(frame, camera, 160, 120, root)
        assert same_size_again is small, "same size must reuse the same photo image"

        resized = renderer.render(frame, camera, 320, 240, root)
        assert resized is not None
        assert resized is not small, "a resize must allocate a fresh photo image"
        assert (resized.width(), resized.height()) == (320, 240)
    finally:
        root.destroy()


def test_pillow_photoimage_write_matches_tkinter_photoimage_write(tmp_path: Path) -> None:
    """expra-mcp's capture_viewport calls ``.write(path, format="png")`` on
    the live viewport's pixel image -- confirm PillowEditorPhotoImage
    produces the identical real Tk-native PNG a plain tkinter.PhotoImage
    would (same underlying Tcl ``<image> write`` command).
    """
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        root = tk.Tk()
    except tk.TclError:
        pygame.quit()
        pytest.skip("no display for real Tk editor presentation")

    try:
        from PIL import Image

        surface = pygame.Surface((3, 3), flags=pygame.SRCALPHA)
        surface.fill((10, 20, 30, 255))
        rgba_bytes = pygame.image.tostring(surface, "RGBA")
        pil_image = Image.frombuffer("RGBA", (3, 3), rgba_bytes, "raw", "RGBA", 0, 1)
        photo = PillowEditorPhotoImage(pil_image, master=root)

        out_path = tmp_path / "capture.png"
        photo.write(str(out_path), format="png")

        assert out_path.exists()
        data = out_path.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        decoded = pygame.image.load(BytesIO(data))
        assert decoded.get_size() == (3, 3)
        assert tuple(decoded.get_at((0, 0))) == (10, 20, 30, 255)
    finally:
        pygame.quit()
        root.destroy()


def test_space_pong_paddles_use_canonical_pixel_path_not_canvas_fallback() -> None:
    """Space Pong's paddles are PrimitiveComponent(kind="rounded_rectangle").

    Before rounded_rectangle backend support existed, frame_textures_available
    rejected it and Space Pong silently fell back to Canvas-vector rendering in
    the editor -- this proves the canonical Pygame pixel path is now genuinely
    active for it, not merely that the primitive doesn't crash.
    """
    pygame = pytest.importorskip("pygame")
    project = Project.load(Path(__file__).parents[1] / "examples" / "space_pong")
    scene = project.load_scene()

    paddles = [
        entity
        for entity in scene.entities
        if entity.name in ("Left Paddle", "Right Paddle")
        and (primitive := entity.get_component(PrimitiveComponent)) is not None
        and primitive.kind == "rounded_rectangle"
    ]
    assert len(paddles) == 2, "expected both paddles to use rounded_rectangle"

    frame = extract_render_frame(scene)
    paddle_ids = {entity.entity_id for entity in paddles}
    frame_paddle_items = [item for item in frame.items if item.key in paddle_ids]
    assert len(frame_paddle_items) == 2
    assert all(item.primitive.kind == "rounded_rectangle" for item in frame_paddle_items)

    pygame.init()
    try:
        service = project.resource_service()
        provider = PygameResourceProvider(pygame, service)
        context = RenderContext(Viewport(0, 0, 320, 240), OrthographicCamera(width=100.0, height=75.0))

        # This is the exact preflight the editor calls before choosing pixel
        # rendering over Canvas fallback -- it must accept rounded_rectangle now.
        assert frame_textures_available(frame, context, provider)

        encoded = _render_editor_frame_to_image(
            frame,
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

        # A real pixel image, not the None that signals Canvas fallback.
        assert encoded is not None
        decoded = pygame.image.load(BytesIO(encoded))
        assert decoded.get_bounding_rect().width > 0
        assert decoded.get_bounding_rect().height > 0
    finally:
        pygame.quit()
