"""The editor's pixel bridge: canonical render (pygame surface -> RGBA -> PIL) -> ``QImage``.

The Qt presentation object must hold the rendered pixels, alpha and dimensions, be
reused/replaced correctly across frames, and own its buffers safely.
"""

from __future__ import annotations

import gc
from pathlib import Path
from types import SimpleNamespace

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import RenderContext, RenderItem, Viewport
from expra_engine.runtime.visual_components import PrimitiveComponent
from expra_engine.ui.editor_pixel_renderer import (
    EditorPixelRenderer,
    render_editor_frame_to_pixel_image,
)
from expra_engine.ui.viewport_render_target import build_editor_render_target
from tests.support.qt_app import ensure_qt_app
from tests.support.texture_project import make_texture_project

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

WIDTH, HEIGHT = 160, 120


def _scene_with_texture_and_primitive(tmp_path: Path):
    project, scene, _asset = make_texture_project(tmp_path)
    rotated = scene.create_entity("rotated primitive", entity_id="rotated")
    rotated.add_component(TransformComponent(x=3.0, rotation=45.0))
    rotated.add_component(PrimitiveComponent(width=1.5, height=0.75, fill=(0.1, 0.8, 0.2, 1.0)))
    return project, extract_render_frame(scene)


def _render(pygame, project, frame, *, factory):
    from expra_engine.runtime.pygame_renderer import PygameResourceProvider

    service = project.resource_service()
    return render_editor_frame_to_pixel_image(
        frame,
        RenderContext(Viewport(0, 0, WIDTH, HEIGHT)),
        width=WIDTH,
        height=HEIGHT,
        resource_service=service,
        resource_provider=PygameResourceProvider(pygame, service),
        pygame_module=pygame,
        image_factory=factory,
    )


def test_pixel_layer_holds_the_rendered_pixels(tmp_path) -> None:
    pygame = pytest.importorskip("pygame")
    from expra_engine.editor.qt.image_bridge import QtEditorImage

    ensure_qt_app()
    project, frame = _scene_with_texture_and_primitive(tmp_path)
    pygame.init()
    try:
        image = _render(pygame, project, frame, factory=QtEditorImage)
        assert image is not None
        assert (image.width(), image.height()) == (WIDTH, HEIGHT)
        opaque = sum(
            not image.transparency_get(x, y) for y in range(0, HEIGHT, 3) for x in range(0, WIDTH, 3)
        )
        assert opaque > 50, "the render must contain real (non-transparent) pixels"
        # the known non-uniform texture quadrants + rotated primitive are present
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


def test_editor_pixel_bridge_culls_each_item_once(monkeypatch) -> None:
    pygame = pytest.importorskip("pygame")
    from expra_engine.runtime import render_math

    monkeypatch.setattr(render_math, "_native_module", None)

    scene = Scene("single cull")
    entity = scene.create_entity("marker", entity_id="marker")
    entity.add_component(TransformComponent())
    entity.add_component(PrimitiveComponent("rectangle"))
    calls = 0
    original = RenderItem.is_visible

    def counted_is_visible(item, context):
        nonlocal calls
        calls += 1
        return original(item, context)

    monkeypatch.setattr(RenderItem, "is_visible", counted_is_visible)
    pygame.init()
    try:
        target = build_editor_render_target(scene, viewport=(64, 48))
        image = render_editor_frame_to_pixel_image(
            target.frame,
            RenderContext(Viewport(0, 0, 64, 48)),
            width=64,
            height=48,
            visible_items=target.items,
            resource_service=None,
            resource_provider=lambda _resource: None,
            pygame_module=pygame,
            image_factory=lambda image: image,
        )

        assert image is not None
        assert calls == 1
    finally:
        pygame.quit()


def test_write_png_exports_the_pixel_layer(tmp_path) -> None:
    pygame = pytest.importorskip("pygame")
    from PIL import Image

    from expra_engine.editor.qt.image_bridge import QtEditorImage

    ensure_qt_app()
    project, frame = _scene_with_texture_and_primitive(tmp_path / "p")
    pygame.init()
    try:
        image = _render(pygame, project, frame, factory=QtEditorImage)
        path = tmp_path / "layer.png"
        image.write(str(path), format="png")
        pixels = Image.open(path).convert("RGBA")
        assert pixels.size == (WIDTH, HEIGHT)
        for y in range(0, HEIGHT, 4):
            for x in range(0, WIDTH, 4):
                red, green, blue, alpha = pixels.getpixel((x, y))
                assert (alpha == 0) == image.transparency_get(x, y), (x, y)
                if alpha:
                    assert (red, green, blue) == image.get(x, y), (x, y)
        cropped = tmp_path / "crop.png"
        image.write(str(cropped), "png", (10, 10, 30, 40))
        assert Image.open(cropped).size == (20, 30)
    finally:
        pygame.quit()


def test_renderer_reuses_and_replaces_the_pixel_image(tmp_path) -> None:
    pytest.importorskip("pygame")
    from expra_engine.editor.qt.image_bridge import QtEditorImage

    ensure_qt_app()
    project, scene, _asset = make_texture_project(tmp_path)
    frame = extract_render_frame(scene)
    camera = SimpleNamespace(position=(0.0, 0.0), _camera=SimpleNamespace(width=10.0, rotation=0.0))
    renderer = EditorPixelRenderer(project.resource_service(), image_factory=QtEditorImage)

    first = renderer.render(frame, camera, WIDTH, HEIGHT)
    second = renderer.render(frame, camera, WIDTH, HEIGHT)
    assert isinstance(first, QtEditorImage)
    assert second is first, "the same image object is repainted in place across frames"
    resized = renderer.render(frame, camera, WIDTH + 20, HEIGHT)
    assert (resized.width(), resized.height()) == (WIDTH + 20, HEIGHT)
    kept = renderer.render(frame, camera, WIDTH + 20, HEIGHT)
    renderer.clear()
    assert renderer.render(frame, camera, WIDTH + 20, HEIGHT) is not kept


def test_qimage_owns_its_buffer_after_sources_are_freed() -> None:
    from PIL import Image

    from expra_engine.editor.qt.image_bridge import (
        QtEditorImage,
        live_image_count,
        pil_image_to_qimage,
        pygame_surface_to_qimage,
    )

    ensure_qt_app()
    gc.collect()
    baseline = live_image_count()
    source = Image.new("RGBA", (64, 48), (10, 20, 30, 255))
    image = QtEditorImage(source)
    qimage = pil_image_to_qimage(source)
    del source
    gc.collect()
    scratch = [bytearray(64 * 48 * 4) for _ in range(50)]  # churn the allocator
    assert image.get(5, 5) == (10, 20, 30)
    assert qimage.pixelColor(5, 5).red() == 10
    assert live_image_count() == baseline + 1
    del scratch
    del image
    gc.collect()
    assert live_image_count() == baseline

    pygame = pytest.importorskip("pygame")
    surface = pygame.Surface((8, 6), pygame.SRCALPHA)
    surface.fill((1, 2, 3, 128))
    converted = pygame_surface_to_qimage(surface)
    del surface
    gc.collect()
    color = converted.pixelColor(0, 0)
    assert (color.red(), color.green(), color.blue(), color.alpha()) == (1, 2, 3, 128)


def test_pixmap_conversion_handles_modes_and_paste_replaces_pixels() -> None:
    from PIL import Image

    from expra_engine.editor.qt.image_bridge import QtEditorImage, pil_image_to_qpixmap

    ensure_qt_app()
    for mode in ("RGB", "RGBA", "L", "P", "LA"):
        pixmap = pil_image_to_qpixmap(Image.new(mode, (7, 5)))
        assert (pixmap.width(), pixmap.height()) == (7, 5)
    image = QtEditorImage(Image.new("RGBA", (4, 4), (255, 0, 0, 255)))
    assert image.get(1, 1) == (255, 0, 0)
    image.paste(Image.new("RGBA", (4, 4), (0, 0, 255, 0)))
    assert image.transparency_get(1, 1) is True


def test_pixel_layer_renders_polygon_and_line_primitives(tmp_path) -> None:
    pygame = pytest.importorskip("pygame")
    from expra_engine.editor.qt.image_bridge import QtEditorImage

    ensure_qt_app()
    project, scene, _asset = make_texture_project(tmp_path)
    face = scene.create_entity("isometric face", entity_id="isometric-face")
    face.add_component(
        PrimitiveComponent(
            kind="polygon",
            points=((-2.0, 0.0), (0.0, -1.0), (2.0, 0.0), (0.0, 1.0)),
            fill=(0.9, 0.2, 0.1, 1.0),
        )
    )
    stroke = scene.create_entity("isometric detail", entity_id="isometric-detail")
    stroke.add_component(TransformComponent(y=2.0))
    stroke.add_component(
        PrimitiveComponent(
            kind="line",
            points=((-2.0, 0.0), (2.0, 0.0)),
            fill=(0.1, 0.9, 0.2, 1.0),
            thickness=1.0,
        )
    )

    pygame.init()
    try:
        image = _render(pygame, project, extract_render_frame(scene), factory=QtEditorImage)
        assert image is not None, "polygon/line frames must stay on the editor pixel path"
        red = image.get(80, 60)
        green = image.get(80, 36)
        assert red[0] > red[1] and red[0] > red[2]
        assert green[1] > green[0] and green[1] > green[2]
    finally:
        pygame.quit()
