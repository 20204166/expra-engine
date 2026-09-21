"""Focused contracts for the renderer-neutral runtime UI tree."""

from __future__ import annotations

import inspect

from expra_engine.runtime.ui import (
    Button,
    GameCanvas,
    Insets,
    Label,
    LayoutSpec,
    Panel,
    Rect,
    UIEvent,
    Viewport,
)


def test_canvas_layout_uses_reference_resolution_safe_area_and_minimum_size() -> None:
    canvas = GameCanvas(reference_resolution=(800, 600))
    panel = Panel(
        "hud",
        layout=LayoutSpec(
            anchor_min=(1.0, 0.0),
            anchor_max=(1.0, 0.0),
            pivot=(1.0, 0.0),
            size=(100.0, 40.0),
            min_size=(120.0, 50.0),
        ),
    )
    canvas.add(panel)

    result = canvas.layout(Viewport(1600, 900), Insets(20, 10, 30, 40))

    rect = result.rect(panel)
    assert rect.x == 1337.5
    assert rect.y == 10.0
    assert rect.width == 232.5
    assert rect.height == 70.83333333333334
    assert canvas.layout(Viewport(0, 0)).rect(canvas) == Rect(0.0, 0.0, 0.0, 0.0)


def test_layout_stretches_children_to_safe_area_and_resize_is_deterministic() -> None:
    canvas = GameCanvas()
    panel = Panel("background", layout=LayoutSpec(anchor_min=(0, 0), anchor_max=(1, 1)))
    canvas.add(panel)

    first = canvas.layout(Viewport(800, 600), Insets(10, 20, 30, 40)).rect(panel)
    second = canvas.layout(Viewport(1600, 1200), Insets(20, 40, 60, 80)).rect(panel)

    assert first == Rect(10.0, 20.0, 760.0, 540.0)
    assert second == Rect(20.0, 40.0, 1520.0, 1080.0)


def test_hit_testing_uses_reverse_child_order_and_ignores_hidden_or_destroyed_nodes() -> None:
    canvas = GameCanvas()
    bottom = Button("bottom", layout=LayoutSpec(size=(100, 50)))
    top = Button("top", layout=LayoutSpec(size=(100, 50)))
    canvas.add(bottom)
    canvas.add(top)
    canvas.layout(Viewport(200, 100))

    assert canvas.hit_test((20, 20)) is top
    top.visible = False
    assert canvas.hit_test((20, 20)) is bottom
    bottom.destroy()
    assert canvas.hit_test((20, 20)) is None


def test_button_states_focus_and_pointer_capture_route_click_once() -> None:
    clicked: list[str] = []
    canvas = GameCanvas()
    button = Button("play", text="Play", layout=LayoutSpec(size=(100, 50)), on_click=lambda: clicked.append("play"))
    canvas.add(button)
    canvas.layout(Viewport(200, 100))

    assert canvas.dispatch(UIEvent("pointer_move", (10, 10))) is button
    assert button.state == "hover"
    assert canvas.dispatch(UIEvent("pointer_down", (10, 10))) is button
    assert button.state == "pressed"
    assert canvas.dispatch(UIEvent("pointer_move", (150, 80))) is button
    assert canvas.dispatch(UIEvent("pointer_up", (150, 80))) is button
    assert clicked == ["play"]
    assert button.state == "focused"
    assert canvas.focused is button


def test_disabled_hidden_and_destroyed_controls_cannot_own_focus() -> None:
    canvas = GameCanvas()
    button = Button("play", layout=LayoutSpec(size=(100, 50)))
    canvas.add(button)
    canvas.layout(Viewport(200, 100))
    canvas.focus(button)
    assert canvas.focused is button

    button.enabled = False
    assert canvas.focused is None
    button.enabled = True
    canvas.focus(button)
    button.visible = False
    assert canvas.focused is None
    button.visible = True
    canvas.focus(button)
    button.destroy()
    assert canvas.focused is None


def test_draw_commands_include_label_panel_button_state_and_nine_slice_data() -> None:
    canvas = GameCanvas()
    panel = Panel("panel", layout=LayoutSpec(size=(200, 100)), nine_slice="frame")
    panel.add(Label("title", text="Line 1\nLine 2", layout=LayoutSpec(size=(100, 40))))
    panel.add(Button("ok", text="OK", layout=LayoutSpec(size=(80, 30))))
    canvas.add(panel)
    canvas.layout(Viewport(400, 300))

    commands = canvas.draw_commands()

    assert [command.kind for command in commands] == ["panel", "label", "button"]
    assert commands[0].nine_slice == "frame"
    assert commands[1].text == "Line 1\nLine 2"
    assert commands[2].state == "normal"


def test_pure_runtime_ui_modules_do_not_import_backend_toolkits() -> None:
    import expra_engine.runtime.ui as ui

    source = inspect.getsource(ui)
    assert "import pygame" not in source
    assert "import tkinter" not in source
