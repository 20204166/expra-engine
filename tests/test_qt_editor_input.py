"""Qt-specific input paths: editor shortcuts, runtime key forwarding, event translation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from expra_engine.core.engine import EngineRunState
from expra_engine.runtime.input import ActionId, PhysicalInput
from tests.support.qt_app import ensure_qt_app, pump_qt, qt_available

pytestmark = [
    pytest.mark.skipif(not qt_available(), reason="PySide6 not installed"),
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
]


def test_qt_key_events_translate_to_viewport_names_and_modifiers() -> None:
    from PySide6.QtCore import Qt

    from expra_engine.editor.qt.canvas import keysym_name, modifier_state

    none = Qt.KeyboardModifier.NoModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    keypad = Qt.KeyboardModifier.KeypadModifier
    assert keysym_name(int(Qt.Key.Key_Q), "q", none) == "q"
    assert keysym_name(int(Qt.Key.Key_F), "F", shift) == "F"
    assert keysym_name(int(Qt.Key.Key_Space), " ", none) == "space"
    assert keysym_name(int(Qt.Key.Key_Equal), "=", none) == "equal"
    assert keysym_name(int(Qt.Key.Key_Plus), "+", keypad) == "KP_Add"
    assert keysym_name(int(Qt.Key.Key_Home), "", none) == "Home"
    assert keysym_name(int(Qt.Key.Key_F5), "", none) == "F5"
    combined = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier
    assert modifier_state(combined) == 0x1 | 0x4
    assert modifier_state(none) == 0


def test_ctrl_z_runs_the_shared_undo_through_a_real_key_event(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    w = window()
    w._act_add_entity()
    pump_qt(20)
    assert len(w._hierarchy._row_state) == 3
    w.activateWindow()
    QTest.qWaitForWindowActive(w)
    QTest.keyClick(w, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    pump_qt(20)
    assert len(w._hierarchy._row_state) == 2
    QTest.keyClick(w, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    pump_qt(20)
    assert len(w._hierarchy._row_state) == 3


def test_runtime_keys_reach_the_engine_input_map_only_while_playing(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    w = window()
    engine = w._engine
    engine.input_map.bind(ActionId("left_up"), PhysicalInput("keyboard", "w"))
    engine.input_map.bind(ActionId("jump"), PhysicalInput("keyboard", "space"))
    w.activateWindow()
    QTest.qWaitForWindowActive(w)

    QTest.keyClick(w, Qt.Key.Key_W)
    pump_qt(10)
    assert not engine.input_map.held_actions  # edit mode: ignored

    w._act_play()
    pump_qt(20)
    assert engine.run_state == EngineRunState.PLAY
    QTest.keyPress(w, Qt.Key.Key_W)
    pump_qt(10)
    assert engine.input_map.is_held("left_up")
    QTest.keyRelease(w, Qt.Key.Key_W)
    pump_qt(10)
    assert not engine.input_map.is_held("left_up")
    QTest.keyPress(w, Qt.Key.Key_Space)
    pump_qt(10)
    assert engine.input_map.is_held("jump")
    QTest.keyRelease(w, Qt.Key.Key_Space)
    QTest.keyClick(w, Qt.Key.Key_F1)  # unconfigured key: no effect
    pump_qt(10)
    assert not engine.input_map.held_actions
    w._act_stop()


def test_canvas_binding_sequences_match_supported_viewport_syntax() -> None:
    from expra_engine.editor.qt.canvas import _Binding

    def event(**kw):
        base = {"state": 0, "num": 0, "keysym": "", "buttons": frozenset()}
        return SimpleNamespace(**{**base, **kw})

    assert _Binding("<Button-1>", print).matches("ButtonPress", event(num=1))
    assert _Binding("<ButtonPress-1>", print).matches("ButtonPress", event(num=1))
    assert not _Binding("<ButtonPress-2>", print).matches("ButtonPress", event(num=1))
    assert _Binding("<ButtonRelease-1>", print).matches("ButtonRelease", event(num=1))
    assert _Binding("<B1-Motion>", print).matches("Motion", event(buttons=frozenset({1})))
    assert not _Binding("<B1-Motion>", print).matches("Motion", event(buttons=frozenset()))
    assert _Binding("<f>", print).matches("KeyPress", event(keysym="f"))
    assert not _Binding("<f>", print).matches("KeyPress", event(keysym="F"))
    assert _Binding("<Control-equal>", print).matches("KeyPress", event(keysym="equal", state=0x4))
    assert not _Binding("<Control-equal>", print).matches("KeyPress", event(keysym="equal"))
    assert _Binding("<KeyPress-space>", print).matches("KeyPress", event(keysym="space"))
    assert _Binding("<MouseWheel>", print).matches("MouseWheel", event())


def test_qt_canvas_item_api_matches_the_viewport_canvas_contract() -> None:
    from expra_engine.editor.qt.canvas import QtCanvas

    ensure_qt_app()
    canvas = QtCanvas()
    canvas.resize(200, 100)
    canvas.show()
    pump_qt(20)
    rect = canvas.create_rectangle(10, 10, 50, 40, fill="#ff0000", outline="", tags=("a", "b"))
    oval = canvas.create_oval(60, 10, 90, 40, fill="#00ff00", tags="c")
    text = canvas.create_text(100, 20, text="hi", tags="t")
    line = canvas.create_line(0, 0, 10, 10, 20, 0, tags="l")
    poly = canvas.create_polygon(0, 0, 4, 0, 4, 4, tags="p")
    assert canvas.type(rect) == "rectangle" and canvas.type(oval) == "oval"
    assert canvas.type(text) == "text" and canvas.type(line) == "line"
    assert canvas.type(poly) == "polygon"
    assert canvas.find_withtag("a") == (rect,) and canvas.find_withtag("b") == (rect,)
    assert canvas.gettags(rect) == ("a", "b")
    assert canvas.coords(rect) == [10.0, 10.0, 50.0, 40.0]
    canvas.coords(rect, 0, 0, 5, 5)
    assert canvas.coords(rect) == [0.0, 0.0, 5.0, 5.0]
    canvas.itemconfig(text, text="changed")
    assert canvas.itemcget(text, "text") == "changed"
    canvas.itemconfigure("c", state="hidden")
    assert canvas.itemcget(oval, "state") == "hidden"
    assert canvas.find_all() == (rect, oval, text, line, poly)
    canvas.tag_raise("a")
    assert canvas.find_all()[-1] == rect
    canvas.tag_lower("a")
    assert canvas.find_all()[0] == rect
    box = canvas.bbox("a")
    assert box is not None and box[0] <= 0 and box[2] >= 5
    assert canvas.bbox("missing") is None
    canvas.delete(rect)
    assert rect not in canvas.find_all()
    canvas.delete("c")
    assert canvas.find_withtag("c") == ()
    canvas.delete("all")
    assert canvas.find_all() == ()
    canvas.close()
