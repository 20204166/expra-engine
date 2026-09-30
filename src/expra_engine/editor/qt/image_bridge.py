"""PIL / pygame → Qt image conversion utilities and the viewport image object.

The canonical render output (pygame surface → RGBA bytes → PIL image) is
handed to Qt as an owning ``QImage``. PySide6 is imported lazily inside each
function so importing this module never loads Qt.
"""

from __future__ import annotations

import weakref
from typing import Any

_LIVE_IMAGES: weakref.WeakSet[Any] = weakref.WeakSet()


def live_image_count() -> int:
    """Number of ``QtEditorImage`` objects still alive (leak probe for editor tooling)."""
    return len(_LIVE_IMAGES)


def pil_image_to_qimage(image: Any) -> Any:
    """Convert a PIL image to a ``QImage`` that owns its pixel buffer.

    Supports RGB and RGBA; other modes are converted to RGBA first. Qt's
    ``QImage(bytes, ...)`` constructor only borrows the buffer, so the result
    is ``copy()``-ed before the temporary bytes go out of scope.
    """
    from PySide6.QtGui import QImage

    if image.mode == "RGBA":
        data = image.tobytes("raw", "RGBA")
        width, height = image.size
        return QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
    if image.mode == "RGB":
        data = image.tobytes("raw", "RGB")
        width, height = image.size
        return QImage(data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
    return pil_image_to_qimage(image.convert("RGBA"))


def pil_image_to_qpixmap(image: Any) -> Any:
    """Convert a PIL Image to a QPixmap (needs a running QGuiApplication)."""
    from PySide6.QtGui import QPixmap

    return QPixmap.fromImage(pil_image_to_qimage(image))


def pygame_surface_to_qimage(surface: Any) -> Any:
    """Convert a pygame Surface to a ``QImage`` that owns its buffer (always RGBA).

    Uses ``pygame.image.tostring``, which needs no video mode, so it is safe in
    headless and test contexts.
    """
    import pygame
    from PySide6.QtGui import QImage

    data = pygame.image.tostring(surface, "RGBA", False)
    width, height = surface.get_size()
    return QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


class QtEditorImage:
    """The live viewport pixel layer, backed by a ``QImage``.

    The surface the pixel bridge and inspection tooling use --
    ``width``/``height``/``paste``/``get``/``transparency_get``/``write`` --
    and the ``image_factory`` the editor viewport hands to ``EditorPixelRenderer``.
    """

    def __init__(self, image: Any) -> None:
        self._qimage = pil_image_to_qimage(image)
        _LIVE_IMAGES.add(self)

    def width(self) -> int:
        return int(self._qimage.width())

    def height(self) -> int:
        return int(self._qimage.height())

    def paste(self, image: Any) -> None:
        self._qimage = pil_image_to_qimage(image)

    def pixmap(self) -> Any:
        from PySide6.QtGui import QPixmap

        return QPixmap.fromImage(self._qimage)

    def qimage(self) -> Any:
        return self._qimage

    def get(self, x: int, y: int) -> tuple[int, int, int]:
        color = self._qimage.pixelColor(x, y)
        return (color.red(), color.green(), color.blue())

    def transparency_get(self, x: int, y: int) -> bool:
        return bool(self._qimage.pixelColor(x, y).alpha() == 0)

    def write(
        self,
        filename: str,
        format: str | None = None,
        from_coords: tuple[int, ...] | None = None,
    ) -> None:
        image = self._qimage
        if from_coords:
            x0, y0, x1, y1 = from_coords
            image = image.copy(x0, y0, x1 - x0, y1 - y0)
        if not image.save(filename, (format or "").upper() or None):
            raise OSError(f"could not write image to {filename}")


__all__ = [
    "QtEditorImage",
    "live_image_count",
    "pil_image_to_qimage",
    "pil_image_to_qpixmap",
    "pygame_surface_to_qimage",
]
