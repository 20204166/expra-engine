"""Tests for Qt image bridge utilities (PIL → QPixmap, pygame → QImage).

All tests run on the Qt offscreen platform to avoid needing a display.
"""

from __future__ import annotations

import pytest

from tests.support.qt_app import ensure_qt_app


@pytest.fixture(scope="module")
def qt_app():
    return ensure_qt_app()


class TestPilImageToQPixmap:
    def test_rgb_image_returns_qpixmap(self, qt_app) -> None:
        from PIL import Image

        from expra_engine.editor.qt.image_bridge import pil_image_to_qpixmap

        img = Image.new("RGB", (10, 8), color=(255, 0, 0))
        pixmap = pil_image_to_qpixmap(img)
        assert not pixmap.isNull()
        assert pixmap.width() == 10
        assert pixmap.height() == 8

    def test_rgba_image_returns_qpixmap(self, qt_app) -> None:
        from PIL import Image

        from expra_engine.editor.qt.image_bridge import pil_image_to_qpixmap

        img = Image.new("RGBA", (4, 4), color=(0, 128, 255, 200))
        pixmap = pil_image_to_qpixmap(img)
        assert not pixmap.isNull()
        assert pixmap.width() == 4
        assert pixmap.height() == 4

    def test_palette_image_converted_via_rgba(self, qt_app) -> None:
        from PIL import Image

        from expra_engine.editor.qt.image_bridge import pil_image_to_qpixmap

        img = Image.new("P", (6, 6))
        pixmap = pil_image_to_qpixmap(img)
        assert not pixmap.isNull()

    def test_pixmap_owns_its_buffer(self, qt_app) -> None:
        """The returned QPixmap must be valid after the PIL image is deleted."""
        from PIL import Image

        from expra_engine.editor.qt.image_bridge import pil_image_to_qpixmap

        img = Image.new("RGBA", (2, 2), color=(1, 2, 3, 4))
        pixmap = pil_image_to_qpixmap(img)
        del img
        assert not pixmap.isNull()
        assert pixmap.width() == 2


class TestPygameSurfaceToQImage:
    def test_rgb_surface_returns_qimage(self, qt_app) -> None:
        import pygame

        from expra_engine.editor.qt.image_bridge import pygame_surface_to_qimage

        pygame.init()
        surface = pygame.Surface((8, 6))
        surface.fill((100, 150, 200))
        qimage = pygame_surface_to_qimage(surface)
        assert not qimage.isNull()
        assert qimage.width() == 8
        assert qimage.height() == 6
        pygame.quit()

    def test_rgba_surface_returns_qimage(self, qt_app) -> None:
        import pygame

        from expra_engine.editor.qt.image_bridge import pygame_surface_to_qimage

        pygame.init()
        surface = pygame.Surface((4, 4), pygame.SRCALPHA)
        surface.fill((255, 0, 0, 128))
        qimage = pygame_surface_to_qimage(surface)
        assert not qimage.isNull()
        assert qimage.width() == 4
        assert qimage.height() == 4
        pygame.quit()

    def test_qimage_owns_its_buffer(self, qt_app) -> None:
        """QImage must remain valid after the pygame surface is deleted."""
        import pygame

        from expra_engine.editor.qt.image_bridge import pygame_surface_to_qimage

        pygame.init()
        surface = pygame.Surface((3, 3))
        surface.fill((0, 0, 0))
        qimage = pygame_surface_to_qimage(surface)
        del surface
        assert not qimage.isNull()
        pygame.quit()
