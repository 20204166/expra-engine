"""Pure runtime UI elements, interaction, and draw commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from expra_engine.ui_model.controls import Button as ButtonState
from expra_engine.ui_model.geometry import Insets, Rect, RectTransform
from expra_engine.ui_model.nine_slice import NineSlice

from .events import UIEvent
from .layout import LayoutResult, LayoutSpec, Viewport


@dataclass(frozen=True)
class UIDrawCommand:
    kind: str
    rect: Rect
    text: str = ""
    state: str = "normal"
    style: Any = None
    nine_slice: Any = None
    font: str = "default"
    font_size: float = 16.0
    align: str = "left"


class UIElement:
    def __init__(
        self,
        name: str,
        *,
        layout: RectTransform | None = None,
        visible: bool = True,
        enabled: bool = True,
        z_index: int = 0,
        focusable: bool = False,
        modal: bool = False,
        style: Any = None,
    ) -> None:
        if not name:
            raise ValueError("UI element name must not be empty")
        self.name = name
        self.layout_spec = layout or LayoutSpec()
        self.visible = visible
        self.enabled = enabled
        self.z_index = z_index
        self.focusable = focusable
        self.modal = modal
        self.style = style
        self.parent: UIElement | None = None
        self.children: list[UIElement] = []
        self.bounds = Rect(0, 0, 0, 0)
        self.destroyed = False

    def add(self, child: UIElement) -> UIElement:
        if child is self or child.parent is not None:
            raise ValueError("UI element already has a parent")
        child.parent = self
        self.children.append(child)
        return child

    def destroy(self) -> None:
        self.destroyed = True
        if self.parent is not None:
            self.parent.children = [child for child in self.parent.children if child is not self]
            self.parent = None

    def _active(self) -> bool:
        return self.visible and self.enabled and not self.destroyed

    def _layout_children(
        self,
        parent: Rect,
        result: dict[str, Rect],
        *,
        safe_area: Insets,
        reference_resolution: tuple[float, float] | None,
    ) -> None:
        for child in self.children:
            child.bounds = child.layout_spec.resolve(
                parent, safe_area=safe_area, reference_resolution=reference_resolution
            )
            result[child.name] = child.bounds
            child._layout_children(
                child.bounds,
                result,
                safe_area=Insets(),
                reference_resolution=reference_resolution,
            )

    def _hit_test(self, point: tuple[float, float]) -> UIElement | None:
        if not self._active() or not (
            self.bounds.x <= point[0] <= self.bounds.x + self.bounds.width
            and self.bounds.y <= point[1] <= self.bounds.y + self.bounds.height
        ):
            return None
        for child in sorted(self.children, key=lambda item: item.z_index, reverse=True):
            hit = child._hit_test(point)
            if hit is not None:
                return hit
        return self if self.focusable else None

    def _commands(self) -> list[UIDrawCommand]:
        commands: list[UIDrawCommand] = []
        if self.visible and not self.destroyed:
            commands.extend(self._own_commands())
            for child in sorted(self.children, key=lambda item: item.z_index):
                commands.extend(child._commands())
        return commands

    def _own_commands(self) -> tuple[UIDrawCommand, ...]:
        return ()


class Panel(UIElement):
    def __init__(self, name: str, *, nine_slice: Any = None, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.nine_slice = nine_slice

    def _own_commands(self) -> tuple[UIDrawCommand, ...]:
        return (UIDrawCommand("panel", self.bounds, style=self.style, nine_slice=self.nine_slice),)


class Label(UIElement):
    def __init__(self, name: str, *, text: str = "", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.text = text

    def _own_commands(self) -> tuple[UIDrawCommand, ...]:
        return (UIDrawCommand("label", self.bounds, text=self.text, style=self.style),)


class Button(UIElement):
    def __init__(self, name: str, *, text: str = "", on_click: Callable[[], None] | None = None, **kwargs: Any) -> None:
        super().__init__(name, focusable=True, **kwargs)
        self.text = text
        self.on_click = on_click
        self.control = ButtonState()

    @property
    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.control.pressed:
            return "pressed"
        if getattr(self, "_focused", False):
            return "focused"
        if self.control.hovered:
            return "hover"
        return "normal"

    def _own_commands(self) -> tuple[UIDrawCommand, ...]:
        style = self.style
        if isinstance(style, dict):
            style = style.get(self.state, style.get("normal"))
        return (UIDrawCommand("button", self.bounds, text=self.text, state=self.state, style=style),)


class GameCanvas(UIElement):
    def __init__(self, name: str = "canvas", *, reference_resolution: tuple[float, float] | None = None, **kwargs: Any) -> None:
        super().__init__(name, layout=RectTransform(anchor_min=(0, 0), anchor_max=(1, 1)), **kwargs)
        self.reference_resolution = reference_resolution
        self._focused: UIElement | None = None
        self.captured: UIElement | None = None
        self.hovered: UIElement | None = None

    def layout(self, viewport: Viewport, safe_area: Insets = Insets()) -> LayoutResult:
        width, height = viewport.width, viewport.height
        self.bounds = Rect(0, 0, width, height)
        rectangles = {self.name: self.bounds}
        self._layout_children(
            self.bounds,
            rectangles,
            safe_area=safe_area,
            reference_resolution=self.reference_resolution,
        )
        return LayoutResult(rectangles)

    def hit_test(self, point: tuple[float, float]) -> UIElement | None:
        for _, child in sorted(
            enumerate(self.children), key=lambda item: (item[1].z_index, item[0]), reverse=True
        ):
            hit = child._hit_test(point)
            if hit is not None:
                return hit
        return None

    @property
    def focused(self) -> UIElement | None:
        if self._focused is not None and not self._focused._active():
            self.focus(None)
        return self._focused

    def focus(self, element: UIElement | None) -> None:
        if element is not None and (not element._active() or not element.focusable):
            element = None
        if self._focused is not None and isinstance(self._focused, Button):
            self._focused._focused = False
        self._focused = element
        if isinstance(element, Button):
            element._focused = True

    def dispatch(self, event: UIEvent) -> UIElement | None:
        if self.focused is not None and not self.focused._active():
            self.focus(None)
        target = self.captured if self.captured is not None and self.captured._active() else None
        if event.kind == "pointer_move" and event.position is not None:
            target = target or self.hit_test(event.position)
            if self.hovered is not target:
                if isinstance(self.hovered, Button):
                    self.hovered.control.update(hovered=False)
                self.hovered = target
                if isinstance(target, Button):
                    target.control.update(hovered=True)
            return target
        if event.kind == "pointer_down" and event.position is not None:
            target = self.hit_test(event.position)
            if target is not None:
                self.captured = target
                self.focus(target)
                if isinstance(target, Button):
                    target.control.update(pressed=True)
            return target
        if event.kind == "pointer_up":
            target = self.captured
            self.captured = None
            if isinstance(target, Button):
                target.control.update(pressed=False)
                if target._active() and event.position is not None:
                    target.on_click() if target.on_click is not None else None
            return target
        if event.kind == "key_down" and self.focused is not None:
            if event.key in ("return", "enter", "space") and isinstance(self.focused, Button):
                if self.focused.on_click is not None:
                    self.focused.on_click()
                return self.focused
            return self.focused
        return self.modal and self or target

    def draw_commands(self) -> tuple[UIDrawCommand, ...]:
        return tuple(self._commands())

    handle_event = dispatch


__all__ = ("Button", "GameCanvas", "Label", "Panel", "UIElement", "UIDrawCommand")
