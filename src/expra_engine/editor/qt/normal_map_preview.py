"""Qt normal-map preview window -- same tabs and controls as ``ui.normal_map_preview``.

``NormalMapPreview`` (views, orientation views, ``render_lit``) is the shared,
toolkit-neutral model built by ``build_normal_map_preview``; only the window
that presents it differs.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from expra_engine.editor.qt.image_bridge import pygame_surface_to_qimage
from expra_engine.ui.normal_map_preview import NormalMapPreview

_MAX_SIZE = 384


def _pixmap(surface: Any) -> QPixmap:
    image = pygame_surface_to_qimage(surface)
    if max(image.width(), image.height()) > _MAX_SIZE:
        image = image.scaled(
            _MAX_SIZE,
            _MAX_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
    return QPixmap.fromImage(image)


class _ClickableLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.on_move: Any = None

    def mousePressEvent(self, event: Any) -> None:
        if self.on_move is not None:
            self.on_move(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event: Any) -> None:
        if self.on_move is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.on_move(event.position().x(), event.position().y())


def show_normal_map_preview(parent: Any, preview: NormalMapPreview, metadata: str) -> QDialog:
    """Present the four preview views in a modeless editor-owned window."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Normal Map Preview")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(metadata))
    tabs = QTabWidget()
    layout.addWidget(tabs)
    labels: dict[str, QLabel] = {}
    lit_state = {
        "x": preview.views["Lit"].get_width() * 0.5,
        "y": preview.views["Lit"].get_height() * 0.5,
    }
    for name, surface in preview.views.items():
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        label: QLabel = _ClickableLabel() if name == "Lit" else QLabel()
        label.setPixmap(_pixmap(surface))
        labels[name] = label
        tab_layout.addWidget(label)
        if name == "Lit":
            controls = QHBoxLayout()
            controls.addWidget(QLabel("Light height"))
            slider = QSlider(Qt.Orientation.Horizontal)
            maximum = max(surface.get_size())
            slider.setRange(0, int(maximum))
            slider.setValue(int(max(1.0, surface.get_width() * 0.5)))
            controls.addWidget(slider)
            tab_layout.addLayout(controls)

            def update_lit(*_args: object, height_slider: QSlider = slider) -> None:
                lit_surface = preview.render_lit(
                    float(lit_state["x"]), float(lit_state["y"]), float(height_slider.value())
                )
                labels["Lit"].setPixmap(_pixmap(lit_surface))

            def move_light(
                x: float, y: float, lit_size: tuple[int, int] = surface.get_size()
            ) -> None:
                pixmap = labels["Lit"].pixmap()
                width, image_height = lit_size
                lit_state["x"] = x / max(1, pixmap.width()) * width - width * 0.5
                lit_state["y"] = image_height * 0.5 - y / max(1, pixmap.height()) * image_height
                update_lit()

            slider.valueChanged.connect(update_lit)
            label.on_move = move_light  # type: ignore[attr-defined]
        elif name == "Orientation test":
            buttons = QHBoxLayout()
            for direction, direction_surface in preview.orientation_views.items():
                button = QPushButton(direction)
                button.clicked.connect(
                    lambda *_a, s=direction_surface: labels["Orientation test"].setPixmap(_pixmap(s))
                )
                buttons.addWidget(button)
            tab_layout.addLayout(buttons)
        tabs.addTab(tab, name)
    dialog.setModal(False)
    dialog.show()
    return dialog


__all__ = ["show_normal_map_preview"]
