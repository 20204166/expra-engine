"""Qt viewport -- Qt frontend for the shared ``ViewportCore``.

All render-target building, retained item model, camera, selection, spatial
edit and input behaviour lives in ``expra_engine.editor.viewport_core``. This module only hosts a ``QtCanvas`` and
supplies ``QtEditorImage`` as the pixel-layer image type.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QVBoxLayout, QWidget

from expra_engine.editor.qt.canvas import QtCanvas
from expra_engine.editor.qt.image_bridge import QtEditorImage
from expra_engine.editor.viewport_core import ViewportCore
from expra_engine.ui.styles import COLORS
from expra_engine.ui.viewport_camera import VIEWPORT_BASE_PPU, ViewportCamera
from expra_engine.ui.viewport_render_target import (
    ColliderOutline,
    EditorRenderTarget,
    build_editor_render_target,
)


class ViewportPanel(ViewportCore, QWidget):
    """Canvas-based editor viewport (Qt)."""

    def __init__(
        self,
        parent: Any = None,
        *,
        colors: dict[str, str] | None = None,
        on_entity_click: Any = None,
        camera_state: dict[str, object] | None = None,
        on_camera_change: Any = None,
        resource_service: Any | None = None,
        observer: Any | None = None,
        on_transform_commit: Any = None,
    ) -> None:
        QWidget.__init__(self, parent)
        c = colors or COLORS
        canvas = QtCanvas(self, bg=c["viewport_bg"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(canvas)
        self._init_viewport(
            canvas,
            colors=c,
            on_entity_click=on_entity_click,
            camera_state=camera_state,
            on_camera_change=on_camera_change,
            resource_service=resource_service,
            observer=observer,
            on_transform_commit=on_transform_commit,
            image_factory=QtEditorImage,
        )
        canvas.on_resize = self._on_resize


__all__ = [
    "VIEWPORT_BASE_PPU",
    "ColliderOutline",
    "EditorRenderTarget",
    "ViewportCamera",
    "ViewportPanel",
    "build_editor_render_target",
]
