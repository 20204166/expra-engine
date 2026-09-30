"""QGraphicsView-backed canvas implementing the drawing surface the viewport uses.

The editor viewport, marker, overlay, lighting, camera-overlay and spatial-edit
code all draw through a small canvas-shaped set of calls (``create_line`` /
``create_rectangle`` / ``create_oval`` / ``create_polygon`` / ``create_text`` /
``create_image``, ``coords``, ``itemconfig``, ``delete``, ``tag_raise`` /
``tag_lower``, ``gettags``, ``bind`` / ``tag_bind``, viewport geometry and
deferred callback scheduling). ``QtCanvas`` implements that shared surface on a
``QGraphicsScene`` so the shared ``ViewportCore`` runs against it, and turns Qt
mouse/wheel/key events into event objects (``x``, ``y``, ``x_root``,
``y_root``, ``delta``, ``num``, ``state``, ``keysym``) dispatched to handlers
registered with event-sequence strings such as ``<Button-1>`` or ``<Control-equal>``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractGraphicsShapeItem,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

_SHIFT_BIT = 0x0001
_CONTROL_BIT = 0x0004
_ALT_BIT = 0x0008

_STIPPLE_ALPHA = {"gray75": 0.75, "gray50": 0.5, "gray25": 0.25, "gray12": 0.12}

_KEYSYMS: dict[int, str] = {
    int(Qt.Key.Key_Space): "space",
    int(Qt.Key.Key_Home): "Home",
    int(Qt.Key.Key_Escape): "Escape",
    int(Qt.Key.Key_Equal): "equal",
    int(Qt.Key.Key_Minus): "minus",
    int(Qt.Key.Key_Plus): "plus",
    int(Qt.Key.Key_Return): "Return",
    int(Qt.Key.Key_Enter): "Return",
    int(Qt.Key.Key_Delete): "Delete",
    int(Qt.Key.Key_Left): "Left",
    int(Qt.Key.Key_Right): "Right",
    int(Qt.Key.Key_Up): "Up",
    int(Qt.Key.Key_Down): "Down",
}


def modifier_state(modifiers: Any) -> int:
    """Translate Qt keyboard modifiers into the X11 ``Event.state`` bits the viewport handlers read."""
    state = 0
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        state |= _SHIFT_BIT
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        state |= _CONTROL_BIT
    if modifiers & Qt.KeyboardModifier.AltModifier:
        state |= _ALT_BIT
    return state


def keysym_name(key: int, text: str, modifiers: Any) -> str:
    """Return the X11-style ``keysym`` name for a Qt key event."""
    keypad = bool(modifiers & Qt.KeyboardModifier.KeypadModifier)
    if keypad and key == int(Qt.Key.Key_Plus):
        return "KP_Add"
    if keypad and key == int(Qt.Key.Key_Minus):
        return "KP_Subtract"
    if key in _KEYSYMS:
        return _KEYSYMS[key]
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        letter = chr(key)
        return letter if modifiers & Qt.KeyboardModifier.ShiftModifier else letter.lower()
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return chr(key)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        return f"F{key - int(Qt.Key.Key_F1) + 1}"
    return text


_MODIFIERS = {"Control": _CONTROL_BIT, "Shift": _SHIFT_BIT, "Alt": _ALT_BIT}


class _Binding:
    """A parsed event sequence such as ``<Control-equal>`` or ``<B1-Motion>``."""

    def __init__(self, sequence: str, handler: Callable[[Any], Any]) -> None:
        self.sequence = sequence
        self.handler = handler
        parts = [p for p in re.split(r"[-\s]+", sequence.strip().strip("<>")) if p]
        self.modifiers = 0
        self.kind = ""
        self.detail = ""
        self.button_held = 0
        rest: list[str] = []
        for part in parts:
            if part in _MODIFIERS:
                self.modifiers |= _MODIFIERS[part]
            elif re.fullmatch(r"B[1-5]", part):
                self.button_held = int(part[1])
            else:
                rest.append(part)
        if rest and rest[0] in {
            "Button",
            "ButtonPress",
            "ButtonRelease",
            "Motion",
            "MouseWheel",
            "KeyPress",
            "KeyRelease",
        }:
            self.kind = rest[0]
            self.detail = rest[1] if len(rest) > 1 else ""
        elif rest:  # bare keysym such as <f>, <Home>, <Escape>
            self.kind = "KeyPress"
            self.detail = rest[0]

    def matches(self, kind: str, event: Any) -> bool:
        wanted = {"Button": "ButtonPress"}.get(self.kind, self.kind)
        if wanted != kind:
            return False
        if self.modifiers & ~int(getattr(event, "state", 0)):
            return False
        if kind in {"ButtonPress", "ButtonRelease"}:
            return not self.detail or self.detail == str(getattr(event, "num", ""))
        if kind == "Motion":
            held = getattr(event, "buttons", frozenset())
            return not self.button_held or self.button_held in held
        if kind in {"KeyPress", "KeyRelease"}:
            return not self.detail or self.detail == getattr(event, "keysym", "")
        return True


def _color(value: str | None) -> QColor | None:
    if not value:
        return None
    return QColor(value)


def _tags(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return tuple(value.split())
    return tuple(str(v) for v in value)


class QtCanvas(QGraphicsView):
    """Canvas-shaped drawing surface on a QGraphicsScene."""

    def __init__(self, parent: Any = None, *, bg: str = "#000000") -> None:
        super().__init__(parent)
        self._qscene = QGraphicsScene(self)
        self.setScene(self._qscene)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QBrush(QColor(bg)))
        self._items: dict[int, QGraphicsItem] = {}
        self._item_tags: dict[int, tuple[str, ...]] = {}
        self._item_meta: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        self._z = 0
        self._bindings: list[_Binding] = []
        self._tag_bindings: dict[str, list[_Binding]] = {}
        self._held_buttons: set[int] = set()
        self._last_pos = QPointF(0, 0)
        self.on_resize: Callable[[], None] | None = None
        self._resize_pending = False

    # ------------------------------------------------------------------
    # Item creation
    # ------------------------------------------------------------------

    def _register(self, item: QGraphicsItem, tags: Any, meta: dict[str, Any]) -> int:
        item_id = self._next_id
        self._next_id += 1
        self._z += 1
        item.setZValue(self._z)
        self._qscene.addItem(item)
        item.setData(0, item_id)
        self._items[item_id] = item
        self._item_tags[item_id] = _tags(tags)
        self._item_meta[item_id] = meta
        return item_id

    def _style_shape(self, item: QAbstractGraphicsShapeItem, options: dict[str, Any]) -> None:
        fill = options.get("fill", "")
        outline = options.get("outline", "#000000")
        width = float(options.get("width", 1) or 1)
        fill_color = _color(fill)
        if fill_color is not None:
            alpha = _STIPPLE_ALPHA.get(options.get("stipple", ""))
            if alpha is not None:
                fill_color.setAlphaF(alpha)
            item.setBrush(QBrush(fill_color))
        else:
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        outline_color = _color(outline)
        if outline_color is None:
            item.setPen(QPen(Qt.PenStyle.NoPen))
        else:
            pen = QPen(outline_color, width)
            pen.setCosmetic(False)
            dash = options.get("dash")
            if dash:
                pen.setDashPattern([float(d) for d in dash])
            item.setPen(pen)

    def create_rectangle(self, x0: float, y0: float, x1: float, y1: float, **options: Any) -> int:
        item = QGraphicsRectItem(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
        self._style_shape(item, options)
        return self._register(item, options.get("tags"), {"kind": "rectangle", "opts": options})

    def create_oval(self, x0: float, y0: float, x1: float, y1: float, **options: Any) -> int:
        item = QGraphicsEllipseItem(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
        self._style_shape(item, options)
        return self._register(item, options.get("tags"), {"kind": "oval", "opts": options})

    def create_polygon(self, *coords: float, **options: Any) -> int:
        item = QGraphicsPolygonItem(QPolygonF(self._points(coords)))
        self._style_shape(item, options)
        return self._register(item, options.get("tags"), {"kind": "polygon", "opts": options})

    def create_line(self, *coords: float, **options: Any) -> int:
        item = QGraphicsPathItem()
        meta = {"kind": "line", "opts": options, "coords": tuple(coords)}
        item_id = self._register(item, options.get("tags"), meta)
        self._style_line(item, options)
        self._set_line_path(item, meta)
        return item_id

    def _style_line(self, item: QGraphicsPathItem, options: dict[str, Any]) -> None:
        color = _color(options.get("fill", "#000000")) or QColor("#000000")
        pen = QPen(color, float(options.get("width", 1) or 1))
        dash = options.get("dash")
        if dash:
            pen.setDashPattern([float(d) for d in dash])
        item.setPen(pen)
        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def _set_line_path(self, item: QGraphicsPathItem, meta: dict[str, Any]) -> None:
        points = self._points(meta["coords"])
        path = QPainterPath()
        if points:
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
            if meta["opts"].get("arrow") in {"last", "both"} and len(points) >= 2:
                self._add_arrow_head(path, points[-2], points[-1])
        item.setPath(path)

    @staticmethod
    def _add_arrow_head(path: QPainterPath, start: QPointF, end: QPointF) -> None:
        import math

        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 8.0
        for offset in (math.radians(155), -math.radians(155)):
            path.moveTo(end)
            path.lineTo(
                QPointF(
                    end.x() + size * math.cos(angle + offset),
                    end.y() + size * math.sin(angle + offset),
                )
            )

    def create_text(self, x: float, y: float, **options: Any) -> int:
        item = QGraphicsSimpleTextItem(str(options.get("text", "")))
        meta = {
            "kind": "text",
            "opts": options,
            "anchor_xy": (float(x), float(y)),
            "anchor": options.get("anchor", "center"),
        }
        item_id = self._register(item, options.get("tags"), meta)
        self._style_text(item, options)
        self._place_text(item, meta)
        return item_id

    def _style_text(self, item: QGraphicsSimpleTextItem, options: dict[str, Any]) -> None:
        color = _color(options.get("fill", "#000000")) or QColor("#000000")
        item.setBrush(QBrush(color))
        font = options.get("font")
        qfont = QFont()
        if isinstance(font, (tuple, list)) and font:
            family = str(font[0])
            if family != "default-font":
                qfont.setFamily(family)
            if len(font) > 1:
                qfont.setPointSize(abs(int(font[1])))
            if any(str(part) == "bold" for part in font[2:]):
                qfont.setBold(True)
        item.setFont(qfont)

    def _place_text(self, item: QGraphicsSimpleTextItem, meta: dict[str, Any]) -> None:
        x, y = meta["anchor_xy"]
        rect = item.boundingRect()
        anchor = meta["anchor"]
        dx = -rect.width() / 2
        dy = -rect.height() / 2
        if "w" in anchor:
            dx = 0
        elif "e" in anchor:
            dx = -rect.width()
        if "n" in anchor:
            dy = 0
        elif "s" in anchor:
            dy = -rect.height()
        item.setPos(x + dx, y + dy)

    def create_image(self, x: float, y: float, **options: Any) -> int:
        item = QGraphicsPixmapItem()
        item.setPos(x, y)
        item.setVisible(options.get("state", "normal") != "hidden")
        return self._register(item, options.get("tags"), {"kind": "image", "opts": options})

    @staticmethod
    def _points(coords: tuple[float, ...]) -> list[QPointF]:
        return [QPointF(coords[i], coords[i + 1]) for i in range(0, len(coords) - 1, 2)]

    # ------------------------------------------------------------------
    # Item lookup / mutation
    # ------------------------------------------------------------------

    def _resolve(self, spec: Any) -> list[int]:
        if isinstance(spec, int):
            return [spec] if spec in self._items else []
        if spec == "all":
            return list(self._items)
        if spec == "current":
            current = self._current_item_id()
            return [current] if current is not None else []
        return [i for i, tags in self._item_tags.items() if spec in tags]

    def _current_item_id(self) -> int | None:
        for item in self._qscene.items(self._last_pos):
            item_id = item.data(0)
            if isinstance(item_id, int) and item_id in self._items:
                return item_id
        return None

    def find_all(self) -> tuple[int, ...]:
        """All item ids in stacking order (lowest first), like ``Canvas.find_all``."""
        return tuple(sorted(self._items, key=lambda i: self._items[i].zValue()))

    def find_withtag(self, spec: Any) -> tuple[int, ...]:
        return tuple(self._resolve(spec))

    def gettags(self, spec: Any) -> tuple[str, ...]:
        ids = self._resolve(spec)
        if not ids:
            return ()
        tags = self._item_tags[ids[0]]
        return (*tags, "current") if spec == "current" else tags

    def type(self, spec: Any) -> str | None:
        ids = self._resolve(spec)
        return self._item_meta[ids[0]]["kind"] if ids else None

    def delete(self, *specs: Any) -> None:
        for spec in specs:
            for item_id in self._resolve(spec):
                item = self._items.pop(item_id, None)
                self._item_tags.pop(item_id, None)
                self._item_meta.pop(item_id, None)
                if item is not None:
                    self._qscene.removeItem(item)

    def coords(self, spec: Any, *values: float) -> list[float] | None:
        ids = self._resolve(spec)
        if not ids:
            return None
        item_id = ids[0]
        item = self._items[item_id]
        meta = self._item_meta[item_id]
        kind = meta["kind"]
        if not values:
            return self._read_coords(item, meta)
        if kind in {"rectangle", "oval"}:
            item.setRect(QRectF(QPointF(values[0], values[1]), QPointF(values[2], values[3])).normalized())  # type: ignore[attr-defined]
        elif kind == "polygon":
            item.setPolygon(QPolygonF(self._points(values)))  # type: ignore[attr-defined]
        elif kind == "line":
            meta["coords"] = tuple(values)
            self._set_line_path(item, meta)  # type: ignore[arg-type]
        elif kind == "text":
            meta["anchor_xy"] = (float(values[0]), float(values[1]))
            self._place_text(item, meta)  # type: ignore[arg-type]
        elif kind == "image":
            item.setPos(values[0], values[1])
        return None

    def _read_coords(self, item: QGraphicsItem, meta: dict[str, Any]) -> list[float]:
        kind = meta["kind"]
        if kind in {"rectangle", "oval"}:
            r = item.rect()  # type: ignore[attr-defined]
            return [r.left(), r.top(), r.right(), r.bottom()]
        if kind == "polygon":
            return [c for p in item.polygon() for c in (p.x(), p.y())]  # type: ignore[attr-defined]
        if kind == "line":
            return list(meta["coords"])
        if kind == "text":
            return list(meta["anchor_xy"])
        return [item.pos().x(), item.pos().y()]

    def itemconfigure(self, spec: Any, **options: Any) -> None:
        for item_id in self._resolve(spec):
            self._configure_item(item_id, options)

    itemconfig = itemconfigure

    def _configure_item(self, item_id: int, options: dict[str, Any]) -> None:
        item = self._items[item_id]
        meta = self._item_meta[item_id]
        kind = meta["kind"]
        meta["opts"] = {**meta["opts"], **options}
        opts = meta["opts"]
        if "state" in options:
            item.setVisible(options["state"] != "hidden")
        if kind == "image":
            if "image" in options:
                image = options["image"]
                pixmap = image.pixmap() if image not in ("", None) else QPixmap()
                item.setPixmap(pixmap)  # type: ignore[attr-defined]
            return
        if kind == "text":
            if "text" in options:
                item.setText(str(options["text"]))  # type: ignore[attr-defined]
            self._style_text(item, opts)  # type: ignore[arg-type]
            self._place_text(item, meta)  # type: ignore[arg-type]
            return
        if kind == "line":
            self._style_line(item, opts)  # type: ignore[arg-type]
            self._set_line_path(item, meta)  # type: ignore[arg-type]
            return
        self._style_shape(item, opts)  # type: ignore[arg-type]

    def itemcget(self, spec: Any, option: str) -> Any:
        ids = self._resolve(spec)
        if not ids:
            return ""
        item = self._items[ids[0]]
        if option == "state":
            return "normal" if item.isVisible() else "hidden"
        return self._item_meta[ids[0]]["opts"].get(option, "")

    def tag_raise(self, tag: Any) -> None:
        for item_id in sorted(self._resolve(tag), key=lambda i: self._items[i].zValue()):
            self._z += 1
            self._items[item_id].setZValue(self._z)

    def tag_lower(self, tag: Any) -> None:
        ids = sorted(self._resolve(tag), key=lambda i: self._items[i].zValue(), reverse=True)
        low = min((it.zValue() for it in self._items.values()), default=0.0)
        for offset, item_id in enumerate(ids, start=1):
            self._items[item_id].setZValue(low - offset)

    def bbox(self, *specs: Any) -> tuple[int, int, int, int] | None:
        ids: list[int] = []
        for spec in specs or ("all",):
            ids.extend(self._resolve(spec))
        rect = QRectF()
        for item_id in ids:
            item = self._items[item_id]
            rect = rect.united(item.mapRectToScene(item.boundingRect()))
        if rect.isNull():
            return None
        return (int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom()))

    # ------------------------------------------------------------------
    # Semantic viewport geometry consumed by the shared editor viewport.
    # ------------------------------------------------------------------

    def viewport_size(self) -> tuple[int, int]:
        viewport = self.viewport()
        return int(viewport.width()), int(viewport.height())

    def global_origin(self) -> tuple[int, int]:
        point = self.viewport().mapToGlobal(self.viewport().rect().topLeft())
        return int(point.x()), int(point.y())

    def schedule_idle(self, callback: Callable[[], None]) -> QTimer:
        """Schedule one callback on the Qt event loop after the current event."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.start(0)
        return timer

    # ------------------------------------------------------------------
    # Event binding / dispatch
    # ------------------------------------------------------------------

    def bind(self, sequence: str, handler: Callable[[Any], Any], add: str | None = None) -> None:
        binding = _Binding(sequence, handler)
        if add != "+":
            self._bindings = [b for b in self._bindings if b.sequence != binding.sequence]
        self._bindings.append(binding)

    def tag_bind(
        self, tag: str, sequence: str, handler: Callable[[Any], Any], add: str | None = None
    ) -> None:
        binding = _Binding(sequence, handler)
        bucket = self._tag_bindings.setdefault(tag, [])
        if add != "+":
            bucket[:] = [b for b in bucket if b.sequence != binding.sequence]
        bucket.append(binding)

    def _dispatch(self, kind: str, event: Any) -> bool:
        """Run widget bindings, then item (tag) bindings; return True if any said "break"."""
        broke = False
        for binding in list(self._bindings):
            if binding.matches(kind, event) and binding.handler(event) == "break":
                broke = True
        if kind in {"ButtonPress", "ButtonRelease", "Motion"}:
            for tag in self.gettags("current"):
                for binding in list(self._tag_bindings.get(tag, ())):
                    if binding.matches(kind, event) and binding.handler(event) == "break":
                        broke = True
        return broke

    def _mouse_event(self, qevent: Any, *, num: int = 0, delta: int = 0) -> Any:
        pos = qevent.position()
        self._last_pos = pos
        global_pos = qevent.globalPosition()
        return SimpleNamespace(
            x=int(pos.x()),
            y=int(pos.y()),
            x_root=int(global_pos.x()),
            y_root=int(global_pos.y()),
            num=num,
            delta=delta,
            state=modifier_state(qevent.modifiers()),
            keysym="",
            buttons=frozenset(self._held_buttons),
            widget=self,
        )

    @staticmethod
    def _button_number(qevent: Any) -> int:
        return {
            Qt.MouseButton.LeftButton: 1,
            Qt.MouseButton.MiddleButton: 2,
            Qt.MouseButton.RightButton: 3,
        }.get(qevent.button(), 0)

    def mousePressEvent(self, event: Any) -> None:
        number = self._button_number(event)
        self._held_buttons.add(number)
        self.setFocus()
        self._dispatch("ButtonPress", self._mouse_event(event, num=number))

    def mouseReleaseEvent(self, event: Any) -> None:
        number = self._button_number(event)
        self._dispatch("ButtonRelease", self._mouse_event(event, num=number))
        self._held_buttons.discard(number)

    def mouseMoveEvent(self, event: Any) -> None:
        self._dispatch("Motion", self._mouse_event(event))

    def wheelEvent(self, event: Any) -> None:
        delta = int(event.angleDelta().y())
        pos = event.position()
        self._last_pos = pos
        global_pos = event.globalPosition()
        tk_event = SimpleNamespace(
            x=int(pos.x()),
            y=int(pos.y()),
            x_root=int(global_pos.x()),
            y_root=int(global_pos.y()),
            num=0,
            delta=delta,
            state=modifier_state(event.modifiers()),
            keysym="",
            buttons=frozenset(self._held_buttons),
            widget=self,
        )
        self._dispatch("MouseWheel", tk_event)
        event.accept()

    def _key_event(self, event: Any) -> Any:
        return SimpleNamespace(
            x=int(self._last_pos.x()),
            y=int(self._last_pos.y()),
            x_root=0,
            y_root=0,
            num=0,
            delta=0,
            state=modifier_state(event.modifiers()),
            keysym=keysym_name(event.key(), event.text(), event.modifiers()),
            buttons=frozenset(self._held_buttons),
            widget=self,
        )

    def keyPressEvent(self, event: Any) -> None:
        if event.isAutoRepeat():
            return
        if not self._dispatch("KeyPress", self._key_event(event)):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: Any) -> None:
        if event.isAutoRepeat():
            return
        self._dispatch("KeyRelease", self._key_event(event))

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._qscene.setSceneRect(0, 0, self.viewport().width(), self.viewport().height())
        if self.on_resize is not None and not self._resize_pending:
            self._resize_pending = True
            self.schedule_idle(self._flush_resize)

    def _flush_resize(self) -> None:
        self._resize_pending = False
        if self.on_resize is not None:
            self.on_resize()


__all__ = ["QtCanvas", "keysym_name", "modifier_state"]
