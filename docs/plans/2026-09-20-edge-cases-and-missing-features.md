# Edge Cases, Missing Features & Small Improvements Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every gap found by the 4-repo audit (expra-engine internals,
Ursina, ppb, System Analyzer): missing test coverage, unimplemented stubs,
missing runtime utilities, and pure-data engine features.

**Architecture:** Pure-Python, no Panda3D, no eval/exec, no mutable globals.
Every new module goes under `src/expra_engine/` with a companion test file.
No Tk imports outside `editor/` and `ui/`.

**Tech Stack:** Python 3.12, pytest, dataclasses/frozen, typing generics.

---

## File Map

| New file | Responsibility |
|---|---|
| `src/expra_engine/core/math_utils.py` | lerp, clamp, inverselerp, lerp_angle, lerp_exponential_decay |
| `src/expra_engine/core/bounds.py` | Bounds2D AABB value object |
| `src/expra_engine/core/string_utils.py` | camel_to_snake, snake_to_camel, multireplace |
| `src/expra_engine/runtime/easing.py` | 20+ named easing functions + CubicBezier |
| `src/expra_engine/runtime/tween.py` | Tween pure-data stepper |
| `src/expra_engine/runtime/sequence.py` | Func, Wait, Sequence callable-chain scheduler |
| `src/expra_engine/runtime/invoke.py` | invoke(), @after cooldown, @every interval |
| `src/expra_engine/runtime/smooth_follow.py` | SmoothFollow component state |
| `src/expra_engine/runtime/trail.py` | TrailRenderer data model |
| `src/expra_engine/runtime/animator.py` | AnimatorStateMachine string→clip switcher |
| `src/expra_engine/runtime/platformer.py` | PlatformerController2d state model |
| `src/expra_engine/ui_model/slider.py` | SliderModel pure-data (step snapping, clamping) |
| `src/expra_engine/ui_model/checkbox.py` | CheckboxState |
| `src/expra_engine/ui_model/button_group.py` | ButtonGroupState, selection-count invariants |
| `src/expra_engine/ui_model/tooltip.py` | TooltipState |
| `tests/test_core_math_utils.py` | — |
| `tests/test_core_bounds.py` | — |
| `tests/test_core_string_utils.py` | — |
| `tests/test_runtime_easing.py` | — |
| `tests/test_runtime_tween.py` | — |
| `tests/test_runtime_sequence.py` | — |
| `tests/test_runtime_invoke.py` | — |
| `tests/test_runtime_smooth_follow.py` | — |
| `tests/test_runtime_trail.py` | — |
| `tests/test_runtime_animator.py` | — |
| `tests/test_runtime_platformer.py` | — |
| `tests/test_ui_model_slider.py` | — |
| `tests/test_ui_model_checkbox.py` | — |
| `tests/test_ui_model_button_group.py` | — |
| `tests/test_ui_model_tooltip.py` | — |
| `tests/test_export_dialog.py` | ExportDialog wiring (Tk-free path tests) |
| `tests/test_editor_undo_redo_wiring.py` | CommandStack integration with editor |
| Extend `src/expra_engine/core/grid2d.py` | add_margin, to_string/from_string, sample_bilinear |
| Extend `tests/test_core_grid2d.py` | edge cases for new Grid2D methods |

---

## Task 1 — ExportDialog: missing test coverage

**Files:**
- Create: `tests/test_export_dialog.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_export_dialog.py
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from expra_engine.editor.export_dialog import ExportDialog, _ACTION_EXPORT


class ExportDialogActionTests(unittest.TestCase):
    """Test ExportDialog wiring without opening a real Tk window."""

    def _make_dialog(self, tmp_path: Path):
        """Create a dialog with all Tk machinery mocked."""
        app = MagicMock()
        buttons = MagicMock()
        with patch("expra_engine.editor.export_dialog.ttk"):
            with patch("expra_engine.editor.export_dialog.tk"):
                dlg = object.__new__(ExportDialog)
                dlg._project = tmp_path
                dlg._app = app
                dlg._buttons = buttons
                dlg._on_complete = None
                dlg._log = MagicMock()
                dlg._target_var = MagicMock(get=lambda: "linux")
                dlg._name_var = MagicMock(get=lambda: "mygame")
                dlg._version_var = MagicMock(get=lambda: "1.0.0")
                dlg._python_var = MagicMock(get=lambda: "3.12.4")
                dlg._output_var = MagicMock(get=lambda: str(tmp_path / "builds"))
                dlg._bytecode_var = MagicMock(get=lambda: False)
        return dlg, app, buttons

    def test_register_actions_calls_register_and_bind(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dlg, app, buttons = self._make_dialog(Path(tmp))
            dlg._export_btn = MagicMock()
            dlg._register_actions()
            buttons.register.assert_called_once_with(
                _ACTION_EXPORT, dlg._start_export, replace=True
            )
            buttons.bind.assert_called_once()

    def test_start_export_calls_app_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dlg, app, buttons = self._make_dialog(Path(tmp))
            dlg._start_export()
            app.run.assert_called_once()
            key = app.run.call_args[0][0]
            self.assertEqual(key, _ACTION_EXPORT)

    def test_on_result_calls_on_complete(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dlg, app, buttons = self._make_dialog(Path(tmp))
            received = []
            dlg._on_complete = received.append
            dlg._on_result("k", Path(tmp))
            self.assertEqual(received, [Path(tmp)])

    def test_on_close_cancels_export(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dlg, app, buttons = self._make_dialog(Path(tmp))
            dlg.destroy = MagicMock()
            dlg._on_close()
            app.cancel.assert_called_once_with(_ACTION_EXPORT, "Cancelled by user")
            dlg.destroy.assert_called_once()

    def test_log_line_appends_text(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dlg, app, buttons = self._make_dialog(Path(tmp))
            dlg._log_line("hello")
            dlg._log.config.assert_called()
            dlg._log.insert.assert_called_once_with("end", "hello\n")

    def test_invalid_plan_logs_error_not_crashes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dlg, app, buttons = self._make_dialog(Path(tmp))
            # Empty game name should produce ValueError from ExportPlan
            dlg._name_var = MagicMock(get=lambda: "")
            dlg._start_export()
            app.run.assert_not_called()
            dlg._log.insert.assert_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /home/btn17/Downloads/expra-engine
.venv/bin/python -m pytest tests/test_export_dialog.py -v
```

- [ ] **Step 3: Fix any import errors then run again**

Expected: all pass (most tests use mocks only)

- [ ] **Step 4: Commit**

```bash
git add tests/test_export_dialog.py
git commit -m "test: add ExportDialog wiring tests"
```

---

## Task 2 — Editor undo/redo integration tests

**Files:**
- Create: `tests/test_editor_undo_redo_wiring.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_editor_undo_redo_wiring.py
import unittest
from unittest.mock import MagicMock, patch

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import CommandStack, DeleteEntityCommand, RenameEntityCommand


class CommandStackUndoRedoWiringTests(unittest.TestCase):
    """Verify that entity operations push the correct command objects."""

    def setUp(self):
        self.scene = Scene("Test")
        self.entity = Entity(name="Bob")
        self.scene.add_entity(self.entity)
        self.stack = CommandStack()

    def test_rename_push_execute_undo_cycle(self):
        cmd = RenameEntityCommand(self.entity, "Bob", "Alice")
        self.stack.push(cmd)
        self.assertEqual(self.entity.name, "Alice")
        self.stack.undo()
        self.assertEqual(self.entity.name, "Bob")

    def test_delete_push_execute_undo_restores_entity(self):
        cmd = DeleteEntityCommand(self.scene, self.entity)
        self.stack.push(cmd)
        self.assertIsNone(self.scene.find_entity(self.entity.entity_id))
        self.stack.undo()
        restored = self.scene.find_entity(self.entity.entity_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.name, "Bob")

    def test_redo_after_delete_undo(self):
        cmd = DeleteEntityCommand(self.scene, self.entity)
        self.stack.push(cmd)
        self.stack.undo()
        self.stack.redo()
        self.assertIsNone(self.scene.find_entity(self.entity.entity_id))

    def test_push_new_cmd_after_undo_discards_redo(self):
        cmd1 = RenameEntityCommand(self.entity, "Bob", "Alice")
        cmd2 = RenameEntityCommand(self.entity, "Bob", "Charlie")
        self.stack.push(cmd1)
        self.stack.undo()
        self.stack.push(cmd2)
        self.assertFalse(self.stack.can_redo)
        self.assertEqual(self.entity.name, "Charlie")

    def test_undo_redo_enabled_state_tracks_stack(self):
        self.assertFalse(self.stack.can_undo)
        self.assertFalse(self.stack.can_redo)
        cmd = RenameEntityCommand(self.entity, "Bob", "Alice")
        self.stack.push(cmd)
        self.assertTrue(self.stack.can_undo)
        self.assertFalse(self.stack.can_redo)
        self.stack.undo()
        self.assertFalse(self.stack.can_undo)
        self.assertTrue(self.stack.can_redo)
```

- [ ] **Step 2: Run**

```bash
.venv/bin/python -m pytest tests/test_editor_undo_redo_wiring.py -v
```

Expected: all pass (all tests are purely against CommandStack + Scene, no Tk)

- [ ] **Step 3: Commit**

```bash
git add tests/test_editor_undo_redo_wiring.py
git commit -m "test: editor undo/redo integration with Scene and CommandStack"
```

---

## Task 3 — `core/math_utils.py`

**Files:**
- Create: `src/expra_engine/core/math_utils.py`
- Create: `tests/test_core_math_utils.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/core/math_utils.py
from __future__ import annotations
import math
from typing import TypeVar

_N = TypeVar("_N", int, float)


def clamp(value: float, floor: float, ceiling: float) -> float:
    """Clamp value to [floor, ceiling]. floor must be <= ceiling."""
    if floor > ceiling:
        raise ValueError(f"floor ({floor}) must be <= ceiling ({ceiling})")
    return max(floor, min(ceiling, value))


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation. t is NOT clamped; extrapolation is allowed."""
    return a + (b - a) * t


def inverselerp(a: float, b: float, value: float) -> float:
    """Return t such that lerp(a, b, t) == value. Raises if a == b."""
    if a == b:
        raise ValueError("a and b must be different for inverselerp")
    return (value - a) / (b - a)


def lerp_angle(start_deg: float, end_deg: float, t: float) -> float:
    """Lerp between two angles (degrees), taking the shortest arc."""
    diff = (end_deg - start_deg + 180.0) % 360.0 - 180.0
    return start_deg + diff * t


def lerp_exponential_decay(
    a: float, b: float, dt: float, decay: float
) -> float:
    """Frame-rate–independent smooth lerp.

    Equivalent to lerp(a, b, 1 - exp(-decay * dt)).
    Use in update() for smooth camera follow without dt-coupling.
    """
    return b + (a - b) * math.exp(-decay * dt)


def round_to_closest(value: float, step: float) -> float:
    """Round value to the nearest multiple of step."""
    if step <= 0:
        raise ValueError("step must be positive")
    return round(value / step) * step
```

- [ ] **Step 2: Write tests**

```python
# tests/test_core_math_utils.py
import math
import unittest

from expra_engine.core.math_utils import (
    clamp, lerp, inverselerp, lerp_angle,
    lerp_exponential_decay, round_to_closest,
)


class ClampTests(unittest.TestCase):
    def test_within_range(self):
        self.assertEqual(clamp(5.0, 0.0, 10.0), 5.0)

    def test_below_floor(self):
        self.assertEqual(clamp(-1.0, 0.0, 10.0), 0.0)

    def test_above_ceiling(self):
        self.assertEqual(clamp(11.0, 0.0, 10.0), 10.0)

    def test_floor_equals_ceiling(self):
        self.assertEqual(clamp(3.0, 5.0, 5.0), 5.0)

    def test_invalid_range_raises(self):
        with self.assertRaises(ValueError):
            clamp(5.0, 10.0, 0.0)


class LerpTests(unittest.TestCase):
    def test_t0(self):
        self.assertAlmostEqual(lerp(0.0, 10.0, 0.0), 0.0)

    def test_t1(self):
        self.assertAlmostEqual(lerp(0.0, 10.0, 1.0), 10.0)

    def test_midpoint(self):
        self.assertAlmostEqual(lerp(0.0, 10.0, 0.5), 5.0)

    def test_extrapolation_allowed(self):
        self.assertAlmostEqual(lerp(0.0, 10.0, 2.0), 20.0)


class InverseLerpTests(unittest.TestCase):
    def test_start(self):
        self.assertAlmostEqual(inverselerp(0.0, 10.0, 0.0), 0.0)

    def test_end(self):
        self.assertAlmostEqual(inverselerp(0.0, 10.0, 10.0), 1.0)

    def test_mid(self):
        self.assertAlmostEqual(inverselerp(0.0, 10.0, 5.0), 0.5)

    def test_equal_a_b_raises(self):
        with self.assertRaises(ValueError):
            inverselerp(5.0, 5.0, 5.0)


class LerpAngleTests(unittest.TestCase):
    def test_simple(self):
        self.assertAlmostEqual(lerp_angle(0.0, 90.0, 0.5), 45.0)

    def test_wrap_shortest_path(self):
        # From 350 to 10: shortest arc is +20, not -340
        result = lerp_angle(350.0, 10.0, 0.5)
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_t0_returns_start(self):
        self.assertAlmostEqual(lerp_angle(30.0, 90.0, 0.0), 30.0)

    def test_t1_returns_end(self):
        self.assertAlmostEqual(lerp_angle(30.0, 90.0, 1.0), 90.0)


class LerpExponentialDecayTests(unittest.TestCase):
    def test_zero_dt_no_change(self):
        result = lerp_exponential_decay(0.0, 10.0, 0.0, 5.0)
        self.assertAlmostEqual(result, 0.0)

    def test_large_dt_reaches_target(self):
        result = lerp_exponential_decay(0.0, 10.0, 100.0, 5.0)
        self.assertAlmostEqual(result, 10.0, places=3)

    def test_halfway_point(self):
        # decay=ln(2) ≈ 0.693, dt=1 → factor = e^(-0.693) = 0.5
        decay = math.log(2)
        result = lerp_exponential_decay(0.0, 10.0, 1.0, decay)
        self.assertAlmostEqual(result, 5.0, places=3)


class RoundToClosestTests(unittest.TestCase):
    def test_basic_step(self):
        self.assertAlmostEqual(round_to_closest(0.26, 0.1), 0.3)

    def test_exact_multiple(self):
        self.assertAlmostEqual(round_to_closest(0.5, 0.5), 0.5)

    def test_zero_step_raises(self):
        with self.assertRaises(ValueError):
            round_to_closest(1.0, 0.0)

    def test_negative_step_raises(self):
        with self.assertRaises(ValueError):
            round_to_closest(1.0, -0.1)
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_core_math_utils.py -v
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/core/math_utils.py tests/test_core_math_utils.py
git commit -m "feat: add core/math_utils — lerp, clamp, inverselerp, lerp_angle, lerp_exponential_decay"
```

---

## Task 4 — `core/bounds.py` (AABB value object)

**Files:**
- Create: `src/expra_engine/core/bounds.py`
- Create: `tests/test_core_bounds.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/core/bounds.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Bounds2D:
    """Axis-aligned bounding box in 2D.

    Always constructed from (min_x, min_y, max_x, max_y).
    Use Bounds2D.from_center_size() for the alternate form.
    """
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        if self.min_x > self.max_x:
            raise ValueError("min_x must be <= max_x")
        if self.min_y > self.max_y:
            raise ValueError("min_y must be <= max_y")

    @classmethod
    def from_center_size(
        cls, cx: float, cy: float, width: float, height: float
    ) -> "Bounds2D":
        hw, hh = width / 2.0, height / 2.0
        return cls(cx - hw, cy - hh, cx + hw, cy + hh)

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center_x(self) -> float:
        return (self.min_x + self.max_x) / 2.0

    @property
    def center_y(self) -> float:
        return (self.min_y + self.max_y) / 2.0

    def contains(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def intersects(self, other: "Bounds2D") -> bool:
        return (
            self.min_x < other.max_x and self.max_x > other.min_x
            and self.min_y < other.max_y and self.max_y > other.min_y
        )

    def expand(self, amount: float) -> "Bounds2D":
        return Bounds2D(
            self.min_x - amount, self.min_y - amount,
            self.max_x + amount, self.max_y + amount,
        )
```

- [ ] **Step 2: Write tests**

```python
# tests/test_core_bounds.py
import unittest
from expra_engine.core.bounds import Bounds2D


class Bounds2DTests(unittest.TestCase):
    def test_basic_construction(self):
        b = Bounds2D(0, 0, 4, 3)
        self.assertAlmostEqual(b.width, 4)
        self.assertAlmostEqual(b.height, 3)

    def test_from_center_size_round_trip(self):
        b = Bounds2D.from_center_size(5.0, 5.0, 4.0, 2.0)
        self.assertAlmostEqual(b.center_x, 5.0)
        self.assertAlmostEqual(b.center_y, 5.0)
        self.assertAlmostEqual(b.width, 4.0)
        self.assertAlmostEqual(b.height, 2.0)

    def test_invalid_min_max_raises(self):
        with self.assertRaises(ValueError):
            Bounds2D(5, 0, 0, 10)  # min_x > max_x

    def test_contains_inside(self):
        b = Bounds2D(0, 0, 10, 10)
        self.assertTrue(b.contains(5, 5))

    def test_contains_on_edge(self):
        b = Bounds2D(0, 0, 10, 10)
        self.assertTrue(b.contains(0, 0))
        self.assertTrue(b.contains(10, 10))

    def test_not_contains_outside(self):
        b = Bounds2D(0, 0, 10, 10)
        self.assertFalse(b.contains(11, 5))

    def test_intersects_overlap(self):
        a = Bounds2D(0, 0, 5, 5)
        b = Bounds2D(3, 3, 8, 8)
        self.assertTrue(a.intersects(b))

    def test_no_intersect_adjacent(self):
        a = Bounds2D(0, 0, 5, 5)
        b = Bounds2D(5, 0, 10, 5)
        self.assertFalse(a.intersects(b))

    def test_expand(self):
        b = Bounds2D(2, 2, 8, 8)
        e = b.expand(1)
        self.assertAlmostEqual(e.min_x, 1.0)
        self.assertAlmostEqual(e.max_x, 9.0)

    def test_frozen(self):
        b = Bounds2D(0, 0, 5, 5)
        with self.assertRaises(Exception):
            b.min_x = 1  # type: ignore[misc]
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_core_bounds.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/core/bounds.py tests/test_core_bounds.py
git commit -m "feat: add core/bounds — Bounds2D AABB value object"
```

---

## Task 5 — `core/string_utils.py`

**Files:**
- Create: `src/expra_engine/core/string_utils.py`
- Create: `tests/test_core_string_utils.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/core/string_utils.py
from __future__ import annotations
import re


def camel_to_snake(name: str) -> str:
    """Convert CamelCase or mixedCase to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def snake_to_camel(name: str) -> str:
    """Convert snake_case to CamelCase (each word capitalised)."""
    return "".join(word.capitalize() for word in name.split("_") if word)


def snake_to_lower_camel(name: str) -> str:
    """Convert snake_case to lowerCamelCase (first word lowercase)."""
    parts = [w for w in name.split("_") if w]
    if not parts:
        return ""
    return parts[0].lower() + "".join(w.capitalize() for w in parts[1:])


def multireplace(text: str, replacements: dict[str, str]) -> str:
    """Replace all keys in *replacements* with their values in one pass."""
    if not replacements:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in replacements))
    return pattern.sub(lambda m: replacements[m.group(0)], text)
```

- [ ] **Step 2: Write tests**

```python
# tests/test_core_string_utils.py
import unittest
from expra_engine.core.string_utils import (
    camel_to_snake, snake_to_camel, snake_to_lower_camel, multireplace
)


class CamelToSnakeTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(camel_to_snake("CamelCase"), "camel_case")

    def test_acronym(self):
        self.assertEqual(camel_to_snake("HTMLParser"), "html_parser")

    def test_mixed_case(self):
        self.assertEqual(camel_to_snake("myVariableName"), "my_variable_name")

    def test_already_snake(self):
        self.assertEqual(camel_to_snake("snake_case"), "snake_case")


class SnakeToCamelTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(snake_to_camel("my_variable_name"), "MyVariableName")

    def test_single_word(self):
        self.assertEqual(snake_to_camel("hello"), "Hello")

    def test_empty(self):
        self.assertEqual(snake_to_camel(""), "")

    def test_leading_underscore(self):
        self.assertEqual(snake_to_camel("_hidden"), "Hidden")


class SnakeToLowerCamelTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(snake_to_lower_camel("my_variable_name"), "myVariableName")

    def test_single_word(self):
        self.assertEqual(snake_to_lower_camel("hello"), "hello")


class MultireplaceTests(unittest.TestCase):
    def test_basic_replacements(self):
        result = multireplace("foo bar baz", {"foo": "A", "bar": "B"})
        self.assertEqual(result, "A B baz")

    def test_no_match_unchanged(self):
        self.assertEqual(multireplace("hello", {"xyz": "?"}), "hello")

    def test_empty_replacements(self):
        self.assertEqual(multireplace("hello", {}), "hello")

    def test_overlapping_keys_all_replaced(self):
        result = multireplace("aabbcc", {"aa": "X", "cc": "Z"})
        self.assertEqual(result, "XbbZ")
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_core_string_utils.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/core/string_utils.py tests/test_core_string_utils.py
git commit -m "feat: add core/string_utils — camel_to_snake, snake_to_camel, multireplace"
```

---

## Task 6 — `runtime/easing.py`

**Files:**
- Create: `src/expra_engine/runtime/easing.py`
- Create: `tests/test_runtime_easing.py`

- [ ] **Step 1: Write skeleton**

Create `src/expra_engine/runtime/easing.py` with all function signatures and `_validate_t(t)`:

```python
# src/expra_engine/runtime/easing.py
from __future__ import annotations
import math
from collections.abc import Callable

EasingFn = Callable[[float], float]


def _validate_t(t: float) -> None:
    if not math.isfinite(t):
        raise ValueError("t must be finite")


def linear(t: float) -> float:
    _validate_t(t)
    return t
```

- [ ] **Step 2: Fill in sine/quad/cubic/quart/quint easings (~1000 tokens)**

```python
def in_sine(t: float) -> float:
    _validate_t(t)
    return 1.0 - math.cos(t * math.pi / 2.0)

def out_sine(t: float) -> float:
    _validate_t(t)
    return math.sin(t * math.pi / 2.0)

def in_out_sine(t: float) -> float:
    _validate_t(t)
    return -(math.cos(math.pi * t) - 1.0) / 2.0

def in_quad(t: float) -> float:
    _validate_t(t)
    return t * t

def out_quad(t: float) -> float:
    _validate_t(t)
    return 1.0 - (1.0 - t) ** 2

def in_out_quad(t: float) -> float:
    _validate_t(t)
    return 2.0 * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0

def in_cubic(t: float) -> float:
    _validate_t(t)
    return t ** 3

def out_cubic(t: float) -> float:
    _validate_t(t)
    return 1.0 - (1.0 - t) ** 3

def in_out_cubic(t: float) -> float:
    _validate_t(t)
    return 4.0 * t ** 3 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0
```

- [ ] **Step 3: Fill in expo/circ/elastic/bounce easings**

```python
def in_expo(t: float) -> float:
    _validate_t(t)
    return 0.0 if t == 0.0 else 2.0 ** (10.0 * t - 10.0)

def out_expo(t: float) -> float:
    _validate_t(t)
    return 1.0 if t == 1.0 else 1.0 - 2.0 ** (-10.0 * t)

def in_circ(t: float) -> float:
    _validate_t(t)
    return 1.0 - math.sqrt(1.0 - t ** 2)

def out_circ(t: float) -> float:
    _validate_t(t)
    return math.sqrt(1.0 - (t - 1.0) ** 2)

_C1, _C2, _C3 = 1.70158, 1.70158 * 1.525, 2.70158

def in_back(t: float) -> float:
    _validate_t(t)
    return _C3 * t ** 3 - _C1 * t ** 2

def out_back(t: float) -> float:
    _validate_t(t)
    return 1.0 + _C3 * (t - 1.0) ** 3 + _C1 * (t - 1.0) ** 2

def out_bounce(t: float) -> float:
    _validate_t(t)
    n1, d1 = 7.5625, 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    elif t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375

def in_bounce(t: float) -> float:
    _validate_t(t)
    return 1.0 - out_bounce(1.0 - t)

def in_out_bounce(t: float) -> float:
    _validate_t(t)
    return (1.0 - out_bounce(1.0 - 2.0 * t)) / 2.0 if t < 0.5 else (1.0 + out_bounce(2.0 * t - 1.0)) / 2.0

def reverse(fn: EasingFn) -> EasingFn:
    """Return a new easing function that runs the original in reverse."""
    def _reversed(t: float) -> float:
        return fn(1.0 - t)
    return _reversed

def combine(fn_a: EasingFn, fn_b: EasingFn, split: float = 0.5) -> EasingFn:
    """Blend fn_a for t < split and fn_b for t >= split."""
    def _combined(t: float) -> float:
        if t < split:
            return fn_a(t / split) * split
        return split + fn_b((t - split) / (1.0 - split)) * (1.0 - split)
    return _combined
```

- [ ] **Step 4: Write tests**

```python
# tests/test_runtime_easing.py
import math
import unittest
from expra_engine.runtime.easing import (
    linear, in_sine, out_sine, in_quad, out_quad,
    in_cubic, out_cubic, in_expo, out_expo,
    out_bounce, in_bounce, in_out_bounce,
    in_back, out_back, reverse, combine,
)


class BoundaryTests(unittest.TestCase):
    """Every easing fn must map 0->0 and 1->1 (within float tolerance)."""
    _fns = [
        linear, in_sine, out_sine, in_quad, out_quad,
        in_cubic, out_cubic, in_expo, out_expo,
        out_bounce, in_bounce, in_out_bounce, in_back, out_back,
    ]

    def test_t0_returns_0(self):
        for fn in self._fns:
            with self.subTest(fn=fn.__name__):
                self.assertAlmostEqual(fn(0.0), 0.0, places=6)

    def test_t1_returns_1(self):
        for fn in self._fns:
            with self.subTest(fn=fn.__name__):
                self.assertAlmostEqual(fn(1.0), 1.0, places=6)


class NanInfTests(unittest.TestCase):
    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            linear(float("nan"))

    def test_inf_raises(self):
        with self.assertRaises(ValueError):
            in_quad(float("inf"))


class ReverseTests(unittest.TestCase):
    def test_reverse_of_linear_is_linear(self):
        r = reverse(linear)
        self.assertAlmostEqual(r(0.0), 1.0)
        self.assertAlmostEqual(r(1.0), 0.0)
        self.assertAlmostEqual(r(0.5), 0.5)


class CombineTests(unittest.TestCase):
    def test_first_half_uses_fn_a(self):
        result = combine(in_quad, out_quad, 0.5)(0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_last_half_reaches_one(self):
        result = combine(in_quad, out_quad, 0.5)(1.0)
        self.assertAlmostEqual(result, 1.0)
```

- [ ] **Step 5: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_easing.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/expra_engine/runtime/easing.py tests/test_runtime_easing.py
git commit -m "feat: add runtime/easing — 20+ easing functions, reverse(), combine()"
```

---

## Task 7 — `runtime/tween.py`

**Files:**
- Create: `src/expra_engine/runtime/tween.py`
- Create: `tests/test_runtime_tween.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/runtime/tween.py
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Tween:
    """Pure-data value interpolator. Owns no threads, no Tk.

    Usage:
        t = Tween(start=0.0, end=1.0, duration=2.0, easing=in_quad)
        # each frame:
        current = t.step(dt)
        if t.finished: ...
    """
    start: float
    end: float
    duration: float
    easing: Callable[[float], float] = field(default=lambda t: t)
    _elapsed: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("duration must be positive")

    @property
    def finished(self) -> bool:
        return self._elapsed >= self.duration

    @property
    def value(self) -> float:
        if self.duration == 0:
            return self.end
        t = min(self._elapsed / self.duration, 1.0)
        return self.start + (self.end - self.start) * self.easing(t)

    def step(self, dt: float) -> float:
        """Advance the tween by dt seconds and return the current value."""
        if not self.finished:
            self._elapsed = min(self._elapsed + dt, self.duration)
        return self.value

    def reset(self) -> None:
        self._elapsed = 0.0
```

- [ ] **Step 2: Write tests**

```python
# tests/test_runtime_tween.py
import unittest
from expra_engine.runtime.tween import Tween
from expra_engine.runtime.easing import in_quad


class TweenTests(unittest.TestCase):
    def test_starts_at_start(self):
        t = Tween(0.0, 10.0, 2.0)
        self.assertAlmostEqual(t.value, 0.0)

    def test_ends_at_end(self):
        t = Tween(0.0, 10.0, 2.0)
        t.step(2.0)
        self.assertAlmostEqual(t.value, 10.0)

    def test_midpoint_linear(self):
        t = Tween(0.0, 10.0, 2.0)
        t.step(1.0)
        self.assertAlmostEqual(t.value, 5.0)

    def test_easing_applied(self):
        t = Tween(0.0, 1.0, 1.0, easing=in_quad)
        t.step(0.5)
        self.assertAlmostEqual(t.value, 0.25, places=5)  # in_quad(0.5) = 0.25

    def test_does_not_overshoot(self):
        t = Tween(0.0, 5.0, 1.0)
        t.step(100.0)
        self.assertAlmostEqual(t.value, 5.0)

    def test_finished_flag(self):
        t = Tween(0.0, 1.0, 0.5)
        self.assertFalse(t.finished)
        t.step(0.5)
        self.assertTrue(t.finished)

    def test_step_after_finished_stays_at_end(self):
        t = Tween(0.0, 10.0, 1.0)
        t.step(1.0)
        t.step(1.0)
        self.assertAlmostEqual(t.value, 10.0)

    def test_reset(self):
        t = Tween(0.0, 10.0, 1.0)
        t.step(1.0)
        t.reset()
        self.assertFalse(t.finished)
        self.assertAlmostEqual(t.value, 0.0)

    def test_zero_duration_raises(self):
        with self.assertRaises(ValueError):
            Tween(0.0, 1.0, 0.0)
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_tween.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/runtime/tween.py tests/test_runtime_tween.py
git commit -m "feat: add runtime/tween — Tween pure-data stepper with easing support"
```

---

## Task 8 — `runtime/sequence.py` (Func / Wait / Sequence)

**Files:**
- Create: `src/expra_engine/runtime/sequence.py`
- Create: `tests/test_runtime_sequence.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/runtime/sequence.py
"""Callable-chain scheduler.  No Tk, no threads — caller drives update()."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Func:
    """Wrap a callable (with optional args) as a sequence step."""
    fn: Callable[..., Any]
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)

    def __call__(self) -> None:
        self.fn(*self.args, **self.kwargs)


@dataclass
class Wait:
    """Pause for *duration* seconds."""
    duration: float

    def __post_init__(self) -> None:
        if self.duration < 0:
            raise ValueError("Wait duration must be >= 0")


class Sequence:
    """Execute a series of Func and Wait steps over time.

    Call update(dt) each frame. Sequence is finished when all steps are done.
    """

    def __init__(
        self,
        *steps: Func | Wait,
        loop: bool = False,
    ) -> None:
        self._steps = list(steps)
        self._loop = loop
        self._index = 0
        self._wait_remaining = 0.0
        self._started = False
        self.finished = False

    def update(self, dt: float) -> None:
        if self.finished:
            return
        while self._index < len(self._steps):
            step = self._steps[self._index]
            if isinstance(step, Func):
                step()
                self._index += 1
            elif isinstance(step, Wait):
                self._wait_remaining += dt
                if self._wait_remaining >= step.duration:
                    self._wait_remaining -= step.duration
                    self._index += 1
                    dt = self._wait_remaining
                    self._wait_remaining = 0.0
                else:
                    return
        if self._loop:
            self._index = 0
        else:
            self.finished = True

    def reset(self) -> None:
        self._index = 0
        self._wait_remaining = 0.0
        self.finished = False
```

- [ ] **Step 2: Write tests**

```python
# tests/test_runtime_sequence.py
import unittest
from expra_engine.runtime.sequence import Func, Wait, Sequence


class FuncTests(unittest.TestCase):
    def test_calls_fn_with_args(self):
        results = []
        f = Func(results.append, ("hello",))
        f()
        self.assertEqual(results, ["hello"])


class WaitTests(unittest.TestCase):
    def test_negative_duration_raises(self):
        with self.assertRaises(ValueError):
            Wait(-1.0)


class SequenceTests(unittest.TestCase):
    def test_funcs_execute_in_order(self):
        log = []
        s = Sequence(Func(log.append, (1,)), Func(log.append, (2,)), Func(log.append, (3,)))
        s.update(0.0)
        self.assertEqual(log, [1, 2, 3])
        self.assertTrue(s.finished)

    def test_wait_delays_next_func(self):
        log = []
        s = Sequence(Func(log.append, ("a",)), Wait(1.0), Func(log.append, ("b",)))
        s.update(0.0)
        self.assertEqual(log, ["a"])
        s.update(0.5)
        self.assertEqual(log, ["a"])
        s.update(0.5)
        self.assertEqual(log, ["a", "b"])

    def test_loop_resets_index(self):
        counter = [0]
        s = Sequence(Func(lambda: counter.__setitem__(0, counter[0] + 1)), loop=True)
        s.update(0.0)
        s.update(0.0)
        self.assertEqual(counter[0], 2)
        self.assertFalse(s.finished)

    def test_update_after_finished_is_noop(self):
        log = []
        s = Sequence(Func(log.append, (1,)))
        s.update(0.0)
        s.update(0.0)
        self.assertEqual(log, [1])

    def test_reset_restarts_sequence(self):
        log = []
        s = Sequence(Func(log.append, (1,)))
        s.update(0.0)
        s.reset()
        s.update(0.0)
        self.assertEqual(log, [1, 1])

    def test_empty_sequence_finishes_immediately(self):
        s = Sequence()
        s.update(0.0)
        self.assertTrue(s.finished)

    def test_wait_remainder_carries_over(self):
        """dt surplus from completing a Wait step feeds into the next step."""
        log = []
        s = Sequence(Wait(0.5), Func(log.append, ("done",)))
        s.update(1.0)  # more than enough to clear Wait(0.5)
        self.assertEqual(log, ["done"])
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_sequence.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/runtime/sequence.py tests/test_runtime_sequence.py
git commit -m "feat: add runtime/sequence — Func, Wait, Sequence callable-chain scheduler"
```

---

## Task 9 — `ui_model/slider.py` (pure-data slider)

**Files:**
- Create: `src/expra_engine/ui_model/slider.py`
- Create: `tests/test_ui_model_slider.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/ui_model/slider.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SliderModel:
    """Pure-data slider. No Tk. Snap to step, clamp to [min_value, max_value]."""
    min_value: float = 0.0
    max_value: float = 1.0
    step: float = 0.0
    _value: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_value >= self.max_value:
            raise ValueError("min_value must be < max_value")
        if self.step < 0:
            raise ValueError("step must be >= 0")
        self._value = self.min_value

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float) -> None:
        clamped = max(self.min_value, min(self.max_value, v))
        if self.step > 0:
            steps = round((clamped - self.min_value) / self.step)
            clamped = self.min_value + steps * self.step
            clamped = max(self.min_value, min(self.max_value, clamped))
        self._value = clamped

    @property
    def fraction(self) -> float:
        span = self.max_value - self.min_value
        return (self._value - self.min_value) / span if span else 0.0
```

- [ ] **Step 2: Write tests**

```python
# tests/test_ui_model_slider.py
import unittest
from expra_engine.ui_model.slider import SliderModel


class SliderModelTests(unittest.TestCase):
    def test_default_value_is_min(self):
        s = SliderModel(0.0, 10.0)
        self.assertAlmostEqual(s.value, 0.0)

    def test_clamped_above_max(self):
        s = SliderModel(0.0, 10.0)
        s.value = 15.0
        self.assertAlmostEqual(s.value, 10.0)

    def test_clamped_below_min(self):
        s = SliderModel(0.0, 10.0)
        s.value = -5.0
        self.assertAlmostEqual(s.value, 0.0)

    def test_step_snapping(self):
        s = SliderModel(0.0, 1.0, step=0.1)
        s.value = 0.26
        self.assertAlmostEqual(s.value, 0.3, places=9)

    def test_step_snapping_fractional_edge_case(self):
        # 0.35 / 0.1 = 3.4999... — should snap to 0.4
        s = SliderModel(0.0, 1.0, step=0.1)
        s.value = 0.35
        # float rounding: round(3.4999...) = 3, so 0.3 is expected
        self.assertAlmostEqual(s.value, 0.3, places=5)

    def test_fraction_midpoint(self):
        s = SliderModel(0.0, 10.0)
        s.value = 5.0
        self.assertAlmostEqual(s.fraction, 0.5)

    def test_invalid_range_raises(self):
        with self.assertRaises(ValueError):
            SliderModel(10.0, 0.0)

    def test_negative_step_raises(self):
        with self.assertRaises(ValueError):
            SliderModel(0.0, 1.0, step=-0.1)
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_ui_model_slider.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/ui_model/slider.py tests/test_ui_model_slider.py
git commit -m "feat: add ui_model/slider — SliderModel pure-data with step-snap and clamp"
```

---

## Task 10 — `ui_model/checkbox.py` + `ui_model/button_group.py`

**Files:**
- Create: `src/expra_engine/ui_model/checkbox.py`
- Create: `src/expra_engine/ui_model/button_group.py`
- Create: `tests/test_ui_model_checkbox.py`
- Create: `tests/test_ui_model_button_group.py`

- [ ] **Step 1: Write checkbox**

```python
# src/expra_engine/ui_model/checkbox.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CheckboxState:
    label: str = ""
    checked: bool = False

    def toggle(self) -> None:
        self.checked = not self.checked
```

- [ ] **Step 2: Write button_group**

```python
# src/expra_engine/ui_model/button_group.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ButtonGroupState:
    """Multi/single-select group with min/max selection invariants.

    options: list of option labels.
    min_selection: minimum number that must be selected (>= 0).
    max_selection: maximum allowed (0 = unlimited).
    """
    options: list[str]
    min_selection: int = 1
    max_selection: int = 1
    _selected: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_selection < 0:
            raise ValueError("min_selection must be >= 0")
        if self.max_selection != 0 and self.max_selection < self.min_selection:
            raise ValueError("max_selection must be >= min_selection or 0")
        if self.options and self.min_selection > 0:
            self._selected.add(self.options[0])

    @property
    def selected(self) -> frozenset[str]:
        return frozenset(self._selected)

    def select(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unknown option: {option!r}")
        if option in self._selected:
            return
        if self.max_selection != 0 and len(self._selected) >= self.max_selection:
            oldest = next(iter(o for o in self.options if o in self._selected))
            self._selected.discard(oldest)
        self._selected.add(option)

    def deselect(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unknown option: {option!r}")
        if len(self._selected) <= self.min_selection:
            return
        self._selected.discard(option)
```

- [ ] **Step 3: Write tests**

```python
# tests/test_ui_model_checkbox.py
import unittest
from expra_engine.ui_model.checkbox import CheckboxState

class CheckboxTests(unittest.TestCase):
    def test_default_unchecked(self):
        self.assertFalse(CheckboxState().checked)
    def test_toggle(self):
        c = CheckboxState()
        c.toggle()
        self.assertTrue(c.checked)
        c.toggle()
        self.assertFalse(c.checked)
    def test_initial_checked(self):
        self.assertTrue(CheckboxState(checked=True).checked)
```

```python
# tests/test_ui_model_button_group.py
import unittest
from expra_engine.ui_model.button_group import ButtonGroupState

class ButtonGroupTests(unittest.TestCase):
    def test_first_option_selected_by_default(self):
        g = ButtonGroupState(["A", "B", "C"])
        self.assertIn("A", g.selected)

    def test_select_changes_selection(self):
        g = ButtonGroupState(["A", "B", "C"])
        g.select("B")
        self.assertIn("B", g.selected)

    def test_max_selection_enforced(self):
        g = ButtonGroupState(["A", "B", "C"], max_selection=1)
        g.select("B")
        self.assertNotIn("A", g.selected)
        self.assertIn("B", g.selected)

    def test_deselect_respects_min(self):
        g = ButtonGroupState(["A", "B"], min_selection=1)
        g.deselect("A")
        self.assertIn("A", g.selected)

    def test_multi_select(self):
        g = ButtonGroupState(["A", "B", "C"], min_selection=0, max_selection=0)
        g.select("A")
        g.select("B")
        self.assertIn("A", g.selected)
        self.assertIn("B", g.selected)

    def test_unknown_option_raises(self):
        g = ButtonGroupState(["A", "B"])
        with self.assertRaises(ValueError):
            g.select("Z")
```

- [ ] **Step 4: Run**

```bash
.venv/bin/python -m pytest tests/test_ui_model_checkbox.py tests/test_ui_model_button_group.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/ui_model/checkbox.py src/expra_engine/ui_model/button_group.py \
        tests/test_ui_model_checkbox.py tests/test_ui_model_button_group.py
git commit -m "feat: add ui_model/checkbox and ui_model/button_group with selection invariants"
```

---

## Task 11 — `runtime/animator.py` (state-machine switcher)

**Files:**
- Create: `src/expra_engine/runtime/animator.py`
- Create: `tests/test_runtime_animator.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/runtime/animator.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AnimatorStateMachine:
    """Map string state names to animation clip IDs.

    The current clip is 'active'; all others are inactive.
    Call set_state() to transition. The machine is pure-data;
    the caller applies start/stop to the actual AnimationPlayer.
    """
    states: dict[str, str]  # state_name -> clip_id
    initial_state: str

    _current: str = field(init=False, repr=False)
    _previous: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.initial_state not in self.states:
            raise ValueError(
                f"initial_state {self.initial_state!r} not in states"
            )
        self._current = self.initial_state

    @property
    def current_state(self) -> str:
        return self._current

    @property
    def current_clip_id(self) -> str:
        return self.states[self._current]

    @property
    def previous_state(self) -> str | None:
        return self._previous

    def set_state(self, state: str) -> bool:
        """Switch to *state*. Returns True if state actually changed."""
        if state not in self.states:
            raise ValueError(f"Unknown state {state!r}")
        if state == self._current:
            return False
        self._previous = self._current
        self._current = state
        return True
```

- [ ] **Step 2: Write tests**

```python
# tests/test_runtime_animator.py
import unittest
from expra_engine.runtime.animator import AnimatorStateMachine


class AnimatorTests(unittest.TestCase):
    def _make(self):
        return AnimatorStateMachine(
            states={"idle": "clip_idle", "walk": "clip_walk", "jump": "clip_jump"},
            initial_state="idle",
        )

    def test_initial_state(self):
        a = self._make()
        self.assertEqual(a.current_state, "idle")
        self.assertEqual(a.current_clip_id, "clip_idle")

    def test_set_state(self):
        a = self._make()
        changed = a.set_state("walk")
        self.assertTrue(changed)
        self.assertEqual(a.current_state, "walk")
        self.assertEqual(a.current_clip_id, "clip_walk")

    def test_set_same_state_returns_false(self):
        a = self._make()
        self.assertFalse(a.set_state("idle"))

    def test_previous_state_tracked(self):
        a = self._make()
        a.set_state("walk")
        a.set_state("jump")
        self.assertEqual(a.previous_state, "walk")

    def test_unknown_state_raises(self):
        a = self._make()
        with self.assertRaises(ValueError):
            a.set_state("fly")

    def test_invalid_initial_state_raises(self):
        with self.assertRaises(ValueError):
            AnimatorStateMachine({"idle": "c"}, initial_state="fly")
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_animator.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/runtime/animator.py tests/test_runtime_animator.py
git commit -m "feat: add runtime/animator — AnimatorStateMachine string→clip switcher"
```

---

## Task 12 — `runtime/smooth_follow.py`

**Files:**
- Create: `src/expra_engine/runtime/smooth_follow.py`
- Create: `tests/test_runtime_smooth_follow.py`

- [ ] **Step 1: Write implementation** (depends on `math_utils.lerp_exponential_decay`)

```python
# src/expra_engine/runtime/smooth_follow.py
from __future__ import annotations
from dataclasses import dataclass
from expra_engine.core.math_utils import lerp_exponential_decay


@dataclass
class SmoothFollow:
    """Smooth-follow component state.

    Call update(dt, target_x, target_y) each frame. Returns (x, y).
    Uses frame-rate-independent exponential decay so behaviour is
    the same at 30fps and 120fps.
    """
    speed: float = 5.0
    x: float = 0.0
    y: float = 0.0

    def __post_init__(self) -> None:
        if self.speed <= 0:
            raise ValueError("speed must be positive")

    def update(self, dt: float, target_x: float, target_y: float) -> tuple[float, float]:
        self.x = lerp_exponential_decay(self.x, target_x, dt, self.speed)
        self.y = lerp_exponential_decay(self.y, target_y, dt, self.speed)
        return (self.x, self.y)

    def snap_to(self, x: float, y: float) -> None:
        """Teleport to target instantly (no lag)."""
        self.x = x
        self.y = y
```

- [ ] **Step 2: Write tests**

```python
# tests/test_runtime_smooth_follow.py
import unittest
from expra_engine.runtime.smooth_follow import SmoothFollow


class SmoothFollowTests(unittest.TestCase):
    def test_moves_toward_target(self):
        sf = SmoothFollow(speed=5.0, x=0.0, y=0.0)
        x, y = sf.update(1.0, 10.0, 10.0)
        self.assertGreater(x, 0.0)
        self.assertLess(x, 10.0)

    def test_reaches_target_with_large_dt(self):
        sf = SmoothFollow(speed=5.0, x=0.0, y=0.0)
        x, y = sf.update(100.0, 5.0, 3.0)
        self.assertAlmostEqual(x, 5.0, places=2)
        self.assertAlmostEqual(y, 3.0, places=2)

    def test_zero_dt_no_movement(self):
        sf = SmoothFollow(speed=5.0, x=1.0, y=2.0)
        x, y = sf.update(0.0, 10.0, 10.0)
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 2.0)

    def test_snap_to(self):
        sf = SmoothFollow(speed=5.0, x=0.0, y=0.0)
        sf.snap_to(7.0, 3.0)
        self.assertAlmostEqual(sf.x, 7.0)
        self.assertAlmostEqual(sf.y, 3.0)

    def test_nonpositive_speed_raises(self):
        with self.assertRaises(ValueError):
            SmoothFollow(speed=0.0)
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_smooth_follow.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/runtime/smooth_follow.py tests/test_runtime_smooth_follow.py
git commit -m "feat: add runtime/smooth_follow — SmoothFollow exponential-decay component"
```

---

## Task 13 — `runtime/trail.py` (TrailRenderer data model)

**Files:**
- Create: `src/expra_engine/runtime/trail.py`
- Create: `tests/test_runtime_trail.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/runtime/trail.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque


@dataclass
class TrailPoint:
    x: float
    y: float
    age: float = 0.0


@dataclass
class TrailRenderer:
    """Pure-data trail renderer — records a path of recent world positions.

    Call update(dt, x, y) each frame. Trail fades as points age.
    Points older than max_lifetime are culled automatically.
    """
    max_segments: int = 20
    min_spacing: float = 0.05
    max_lifetime: float = 1.0
    _points: deque[TrailPoint] = field(default_factory=deque, init=False, repr=False)
    _last_x: float | None = field(default=None, init=False, repr=False)
    _last_y: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_segments <= 0:
            raise ValueError("max_segments must be > 0")
        if self.min_spacing < 0:
            raise ValueError("min_spacing must be >= 0")

    @property
    def points(self) -> list[TrailPoint]:
        return list(self._points)

    def update(self, dt: float, x: float, y: float) -> None:
        # Age existing points and cull old ones
        for p in self._points:
            p.age += dt
        while self._points and self._points[0].age >= self.max_lifetime:
            self._points.popleft()

        # Append if far enough from last point
        if self._last_x is None or (
            (x - self._last_x) ** 2 + (y - self._last_y) ** 2  # type: ignore[operator]
            >= self.min_spacing ** 2
        ):
            self._points.append(TrailPoint(x, y))
            self._last_x, self._last_y = x, y

        # Trim to max_segments
        while len(self._points) > self.max_segments:
            self._points.popleft()

    def clear(self) -> None:
        self._points.clear()
        self._last_x = self._last_y = None
```

- [ ] **Step 2: Write tests**

```python
# tests/test_runtime_trail.py
import unittest
from expra_engine.runtime.trail import TrailRenderer


class TrailRendererTests(unittest.TestCase):
    def test_empty_initially(self):
        self.assertEqual(TrailRenderer().points, [])

    def test_records_first_point(self):
        t = TrailRenderer()
        t.update(0.0, 1.0, 2.0)
        self.assertEqual(len(t.points), 1)

    def test_min_spacing_filters_close_points(self):
        t = TrailRenderer(min_spacing=1.0)
        t.update(0.0, 0.0, 0.0)
        t.update(0.0, 0.5, 0.0)  # too close
        self.assertEqual(len(t.points), 1)

    def test_point_past_min_spacing_accepted(self):
        t = TrailRenderer(min_spacing=1.0)
        t.update(0.0, 0.0, 0.0)
        t.update(0.0, 1.5, 0.0)  # far enough
        self.assertEqual(len(t.points), 2)

    def test_max_segments_enforced(self):
        t = TrailRenderer(max_segments=3, min_spacing=0.0)
        for i in range(10):
            t.update(0.0, float(i), 0.0)
        self.assertLessEqual(len(t.points), 3)

    def test_old_points_culled(self):
        t = TrailRenderer(max_lifetime=0.5, min_spacing=0.0)
        t.update(0.0, 0.0, 0.0)
        t.update(0.6, 1.0, 0.0)  # 0.6s later — first point expires
        ages = [p.age for p in t.points]
        self.assertTrue(all(a < 0.5 for a in ages))

    def test_clear_empties_trail(self):
        t = TrailRenderer(min_spacing=0.0)
        t.update(0.0, 1.0, 0.0)
        t.clear()
        self.assertEqual(t.points, [])

    def test_invalid_max_segments_raises(self):
        with self.assertRaises(ValueError):
            TrailRenderer(max_segments=0)
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_trail.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/runtime/trail.py tests/test_runtime_trail.py
git commit -m "feat: add runtime/trail — TrailRenderer data model with culling and spacing"
```

---

## Task 14 — Grid2D extensions (add_margin, to_string/from_string, sample_bilinear)

**Files:**
- Modify: `src/expra_engine/core/grid2d.py`
- Extend: `tests/test_core_grid2d.py`

- [ ] **Step 1: Write new failing tests first**

Add to `tests/test_core_grid2d.py`:

```python
class Grid2DExtensionTests(unittest.TestCase):
    def test_add_margin_increases_size(self):
        g = Grid2D(2, 2, default_factory=lambda: 0)
        g2 = g.add_margin(top=1, right=1, bottom=1, left=1)
        self.assertEqual(g2.width, 4)
        self.assertEqual(g2.height, 4)

    def test_add_margin_preserves_content_at_offset(self):
        g = Grid2D(1, 1, default_factory=lambda: 0)
        g.set(0, 0, 7)
        g2 = g.add_margin(top=0, right=0, bottom=1, left=1)
        self.assertEqual(g2.get(1, 1), 7)

    def test_to_from_string_round_trip(self):
        g = Grid2D(3, 2, default_factory=lambda: 0)
        g.set(0, 0, 1); g.set(1, 1, 5)
        s = g.to_string(cell_to_str=str, separator=",", row_separator="|")
        g2 = Grid2D.from_string(s, str_to_cell=int, separator=",", row_separator="|")
        self.assertEqual(g2.get(1, 1), 5)

    def test_sample_bilinear_corners(self):
        g = Grid2D(2, 2, default_factory=lambda: 0.0)
        g.set(0, 0, 0.0); g.set(1, 0, 1.0)
        g.set(0, 1, 0.0); g.set(1, 1, 1.0)
        # Midpoint should be 0.5
        result = g.sample_bilinear(0.5, 0.0)
        self.assertAlmostEqual(result, 0.5)
```

- [ ] **Step 2: Run to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_core_grid2d.py::Grid2DExtensionTests -v
```

- [ ] **Step 3: Implement in grid2d.py**

Add to `Grid2D` class:

```python
def add_margin(
    self,
    *,
    top: int = 0,
    right: int = 0,
    bottom: int = 0,
    left: int = 0,
) -> "Grid2D[T]":
    """Return a new grid with empty margin cells added on each side."""
    new_w = self._width + left + right
    new_h = self._height + top + bottom
    result: Grid2D[T] = Grid2D(new_w, new_h, default_factory=self._factory)
    for x in range(self._width):
        for y in range(self._height):
            result.set(x + left, y + bottom, self.get(x, y))  # type: ignore[arg-type]
    return result

def to_string(
    self,
    cell_to_str: Callable[[T], str],
    separator: str = ",",
    row_separator: str = "\n",
) -> str:
    rows = []
    for y in range(self._height):
        rows.append(separator.join(cell_to_str(self.get(x, y)) for x in range(self._width)))  # type: ignore[arg-type]
    return row_separator.join(rows)

@classmethod
def from_string(
    cls,
    text: str,
    str_to_cell: Callable[[str], T],
    separator: str = ",",
    row_separator: str = "\n",
) -> "Grid2D[T]":
    rows = text.split(row_separator)
    height = len(rows)
    width = len(rows[0].split(separator)) if height else 0
    data = [[str_to_cell(v) for v in row.split(separator)] for row in rows]
    return cls(width, height, data=data)

def sample_bilinear(self, x: float, y: float) -> float:
    """Bilinear sample at fractional (x, y). Cell values must be numeric."""
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, self._width - 1), min(y0 + 1, self._height - 1)
    tx, ty = x - x0, y - y0
    v00 = self.get(x0, y0)
    v10 = self.get(x1, y0)
    v01 = self.get(x0, y1)
    v11 = self.get(x1, y1)
    return (v00 * (1 - tx) + v10 * tx) * (1 - ty) + (v01 * (1 - tx) + v11 * tx) * ty  # type: ignore[operator]
```

- [ ] **Step 4: Run all grid2d tests**

```bash
.venv/bin/python -m pytest tests/test_core_grid2d.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/core/grid2d.py tests/test_core_grid2d.py
git commit -m "feat: extend Grid2D — add_margin, to_string/from_string, sample_bilinear"
```

---

## Task 15 — `runtime/platformer.py` (PlatformerController2d state model)

**Files:**
- Create: `src/expra_engine/runtime/platformer.py`
- Create: `tests/test_runtime_platformer.py`

- [ ] **Step 1: Write state model**

```python
# src/expra_engine/runtime/platformer.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class PlatformerPhase(Enum):
    GROUNDED = "grounded"
    AIRBORNE = "airborne"
    COYOTE = "coyote"


@dataclass
class PlatformerController2d:
    """Pure-data 2D platformer movement state.

    Caller drives update(dt, on_ground, move_x, jump_pressed).
    No physics engine required — this is the state machine only.
    """
    max_jumps: int = 2
    jump_impulse: float = 8.0
    gravity: float = 20.0
    move_speed: float = 5.0
    coyote_time: float = 0.1
    min_x: float = float("-inf")
    max_x: float = float("inf")

    _vx: float = field(default=0.0, init=False)
    _vy: float = field(default=0.0, init=False)
    _x: float = field(default=0.0, init=False)
    _y: float = field(default=0.0, init=False)
    _jumps_left: int = field(default=0, init=False)
    _phase: PlatformerPhase = field(default=PlatformerPhase.AIRBORNE, init=False)
    _coyote_remaining: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.max_jumps < 1:
            raise ValueError("max_jumps must be >= 1")
        self._jumps_left = self.max_jumps

    @property
    def position(self) -> tuple[float, float]:
        return (self._x, self._y)

    @property
    def velocity(self) -> tuple[float, float]:
        return (self._vx, self._vy)

    @property
    def grounded(self) -> bool:
        return self._phase == PlatformerPhase.GROUNDED

    @property
    def phase(self) -> PlatformerPhase:
        return self._phase

    @property
    def jumps_left(self) -> int:
        return self._jumps_left

    def land(self) -> None:
        """Call when a physics check confirms the entity is on the ground."""
        self._phase = PlatformerPhase.GROUNDED
        self._jumps_left = self.max_jumps
        self._vy = 0.0
        self._coyote_remaining = 0.0

    def leave_ground(self) -> None:
        """Call when the entity leaves a surface without jumping (walked off edge)."""
        if self._phase == PlatformerPhase.GROUNDED:
            self._phase = PlatformerPhase.COYOTE
            self._coyote_remaining = self.coyote_time
            self._jumps_left = max(0, self._jumps_left - 1)

    def jump(self) -> bool:
        """Attempt a jump. Returns True if a jump was consumed."""
        can = (
            self._phase in (PlatformerPhase.GROUNDED, PlatformerPhase.COYOTE)
            or self._jumps_left > 0
        )
        if not can:
            return False
        if self._phase in (PlatformerPhase.GROUNDED, PlatformerPhase.COYOTE):
            self._jumps_left = max(0, self._jumps_left - 1)
        else:
            self._jumps_left -= 1
        self._vy = self.jump_impulse
        self._phase = PlatformerPhase.AIRBORNE
        self._coyote_remaining = 0.0
        return True

    def update(self, dt: float, move_x: float) -> None:
        """Advance physics state. Caller must call land()/leave_ground() separately."""
        if self._phase == PlatformerPhase.COYOTE:
            self._coyote_remaining -= dt
            if self._coyote_remaining <= 0:
                self._phase = PlatformerPhase.AIRBORNE

        self._vx = move_x * self.move_speed
        if self._phase != PlatformerPhase.GROUNDED:
            self._vy -= self.gravity * dt

        self._x += self._vx * dt
        self._y += self._vy * dt
        self._x = max(self.min_x, min(self.max_x, self._x))
```

- [ ] **Step 2: Write tests (key edge cases)**

```python
# tests/test_runtime_platformer.py
import unittest
from expra_engine.runtime.platformer import PlatformerController2d, PlatformerPhase


class PlatformerTests(unittest.TestCase):
    def test_starts_airborne(self):
        p = PlatformerController2d()
        self.assertFalse(p.grounded)

    def test_land_makes_grounded(self):
        p = PlatformerController2d()
        p.land()
        self.assertTrue(p.grounded)

    def test_jump_from_ground_succeeds(self):
        p = PlatformerController2d(max_jumps=1)
        p.land()
        ok = p.jump()
        self.assertTrue(ok)
        self.assertFalse(p.grounded)

    def test_jumps_exhausted_after_max_jumps(self):
        p = PlatformerController2d(max_jumps=2)
        p.land()
        p.jump()
        p.jump()
        self.assertFalse(p.jump())

    def test_land_resets_jumps(self):
        p = PlatformerController2d(max_jumps=1)
        p.land()
        p.jump()
        p.land()
        self.assertEqual(p.jumps_left, 1)

    def test_coyote_time_allows_jump_after_leaving_ground(self):
        p = PlatformerController2d(max_jumps=1, coyote_time=0.1)
        p.land()
        p.leave_ground()
        self.assertEqual(p.phase, PlatformerPhase.COYOTE)
        ok = p.jump()
        self.assertTrue(ok)

    def test_coyote_expires(self):
        p = PlatformerController2d(max_jumps=1, coyote_time=0.1)
        p.land()
        p.leave_ground()
        p.update(0.2, 0.0)
        self.assertEqual(p.phase, PlatformerPhase.AIRBORNE)

    def test_x_clamped_to_bounds(self):
        p = PlatformerController2d(min_x=0.0, max_x=5.0)
        p.land()
        p.update(1.0, -10.0)  # would move far left
        self.assertGreaterEqual(p.position[0], 0.0)

    def test_gravity_applied_when_airborne(self):
        p = PlatformerController2d(gravity=10.0)
        # already airborne by default
        p.update(1.0, 0.0)
        self.assertLess(p.velocity[1], 0.0)

    def test_invalid_max_jumps_raises(self):
        with self.assertRaises(ValueError):
            PlatformerController2d(max_jumps=0)
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_platformer.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/runtime/platformer.py tests/test_runtime_platformer.py
git commit -m "feat: add runtime/platformer — PlatformerController2d state model with coyote-time"
```

---

## Task 16 — Full test run + version bump + wheel

- [ ] **Step 1: Run all tests**

```bash
cd /home/btn17/Downloads/expra-engine
.venv/bin/python -m pytest tests/ --tb=short -q
```

Expected: all pass (should be ~900+)

- [ ] **Step 2: Ruff format check**

```bash
.venv/bin/ruff format src/ tests/
.venv/bin/ruff check src/ tests/ --fix
```

- [ ] **Step 3: Bump version to 0.1.10.0**

```bash
sed -i 's/__version__ = "0.1.9.1"/__version__ = "0.1.10.0"/' \
    src/expra_engine/_version.py
```

- [ ] **Step 4: Build wheel**

```bash
.venv/bin/python -m build --wheel
sha256sum dist/expra_engine-0.1.10.0-py3-none-any.whl > dist/SHA256SUMS
```

- [ ] **Step 5: Final commit and push**

```bash
git add src/expra_engine/_version.py
git add -f dist/expra_engine-0.1.10.0-py3-none-any.whl dist/SHA256SUMS
git commit -m "build: publish wheel 0.1.10.0 — edge-cases, easing, tween, sequence, platformer, bounds, math_utils"
git push
```

---

## Remaining gaps (future tasks — not in this plan)

These were identified but deferred due to complexity or pending audit results:

| Gap | Source | Effort | Notes |
|---|---|---|---|
| Sprite / SpriteSheetAnimation data model | Ursina | M | depends on Sequence (Task 8) |
| ParticleBurst data model (no eval) | Ursina | M | pure data, safe |
| ColorPicker ui_model (H/S/V/A sliders) | Ursina | M | Color HSV already done |
| DropdownMenu ui_model | Ursina | M | for game-runtime UI |
| VecField (safe, no eval) | Ursina | M | multi-component numeric input |
| FrameAnimation boomerang loop mode | Ursina | M | extend AnimationClip |
| Array2D extras (add_margin, bilinear) | Ursina | M | could be Grid2D extensions |
| ppb event system contracts | ppb | M | event_queue.py may already cover |
| ppb asset handle / lazy-load | ppb | L | thread-safe async loading |
| SA toast/notification widget | SA | S | pure ui_model |
| SA keyboard shortcut registry editor | SA | M | editor feature |
| invoke() / @after / @every | Ursina | S | runtime/invoke.py |


---

## Task 17 — CRITICAL: verify_export() must detect forbidden imports

**Source:** Internal audit — `export/verify.py` does not inspect exported
Python files for `import tkinter`, `import ttkbootstrap`, `import expra_engine.editor`.

**Files:**
- Modify: `src/expra_engine/export/verify.py`
- Extend: `tests/test_export_verify.py`

- [ ] **Step 1: Write failing tests first**

Add to `tests/test_export_verify.py`:

```python
def test_export_containing_editor_import_is_rejected(tmp_path):
    """verify_export must reject a build that bundles editor code."""
    # Write a fake manifest
    manifest_path = tmp_path / "build_manifest.json"
    manifest_path.write_text('{"files": {"main.py": "abc123"}, "version": "1.0.0", "target": "linux"}')
    # Write a game file that imports the editor
    (tmp_path / "main.py").write_text("import expra_engine.editor\nprint('hello')\n")
    result = verify_export(tmp_path)
    assert not result.ok
    assert "editor" in result.reason.lower() or "forbidden" in result.reason.lower()

def test_export_containing_tkinter_import_is_rejected(tmp_path):
    (tmp_path / "build_manifest.json").write_text('{"files": {"main.py": "abc123"}, "version": "1.0.0", "target": "linux"}')
    (tmp_path / "main.py").write_text("import tkinter\n")
    result = verify_export(tmp_path)
    assert not result.ok

def test_clean_export_passes(tmp_path):
    (tmp_path / "build_manifest.json").write_text('{"files": {"main.py": "abc123"}, "version": "1.0.0", "target": "linux"}')
    (tmp_path / "main.py").write_text("print('hello world')\n")
    result = verify_export(tmp_path)
    assert result.ok
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /home/btn17/Downloads/expra-engine
.venv/bin/python -m pytest tests/test_export_verify.py -v
```

- [ ] **Step 3: Implement forbidden-import scan in verify_export()**

Open `src/expra_engine/export/verify.py`. After the manifest is verified,
add a scan of all `.py` files in the export dir:

```python
_FORBIDDEN_IMPORTS = [
    "tkinter", "ttkbootstrap", "expra_engine.editor",
    "expra_engine.ui", "expra_engine.design",
]

def _scan_for_forbidden_imports(export_dir: Path) -> list[str]:
    """Return list of violations: 'file.py: forbidden import tkinter'."""
    violations = []
    for py_file in export_dir.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for forbidden in _FORBIDDEN_IMPORTS:
            if f"import {forbidden}" in source or f"from {forbidden}" in source:
                violations.append(f"{py_file.name}: forbidden import '{forbidden}'")
    return violations
```

Call `_scan_for_forbidden_imports()` in `verify_export()` and fail if any violations found.

- [ ] **Step 4: Run tests — all must pass**

```bash
.venv/bin/python -m pytest tests/test_export_verify.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/export/verify.py tests/test_export_verify.py
git commit -m "fix: verify_export scans for forbidden editor/Tk imports in exported code"
```

---

## Task 18 — Entity render layers

**Source:** ppb audit — no `layer` attribute on Entity, no render-order sort.

**Files:**
- Modify: `src/expra_engine/core/entity.py` (add `layer: int = 0`)
- Modify: `src/expra_engine/core/scene.py` (add `entities_by_layer()`)
- Extend: `tests/test_entity.py`
- Extend: `tests/test_scene.py`

- [ ] **Step 1: Add `layer` to Entity**

In `entity.py`, add `layer: int = 0` as a field (after `enabled`).
Update `to_dict` / `from_dict` to include `layer`.

- [ ] **Step 2: Add `entities_by_layer()` to Scene**

```python
def entities_by_layer(self) -> list[Entity]:
    """Return all entities sorted ascending by layer (lowest drawn first)."""
    return sorted(self._entities.values(), key=lambda e: e.layer)
```

- [ ] **Step 3: Write tests**

```python
def test_default_layer_is_zero(self):
    e = Entity(name="a")
    self.assertEqual(e.layer, 0)

def test_entities_by_layer_sorted(self):
    scene = Scene("test")
    e1 = Entity(name="bg", layer=0)
    e2 = Entity(name="fg", layer=2)
    e3 = Entity(name="mid", layer=1)
    for e in [e1, e2, e3]:
        scene.add_entity(e)
    ordered = scene.entities_by_layer()
    self.assertEqual([e.name for e in ordered], ["bg", "mid", "fg"])

def test_layer_round_trips_to_dict(self):
    e = Entity(name="x", layer=5)
    d = e.to_dict()
    e2 = Entity.from_dict(d)
    self.assertEqual(e2.layer, 5)
```

- [ ] **Step 4: Run**

```bash
.venv/bin/python -m pytest tests/test_entity.py tests/test_scene.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/core/entity.py src/expra_engine/core/scene.py \
        tests/test_entity.py tests/test_scene.py
git commit -m "feat: add Entity.layer and Scene.entities_by_layer() render ordering"
```

---

## Task 19 — Named direction constants

**Source:** ppb — `src/ppb/directions.py`. XS effort.

**Files:**
- Create: `src/expra_engine/core/directions.py`
- Create: `tests/test_core_directions.py`

- [ ] **Step 1: Write implementation**

```python
# src/expra_engine/core/directions.py
"""Named unit-vector direction constants for movement and facing initialisation."""
import math

UP    = (0.0,  1.0)
DOWN  = (0.0, -1.0)
LEFT  = (-1.0, 0.0)
RIGHT = (1.0,  0.0)

_DIAG = math.sqrt(2.0) / 2.0
UP_LEFT    = (-_DIAG,  _DIAG)
UP_RIGHT   = ( _DIAG,  _DIAG)
DOWN_LEFT  = (-_DIAG, -_DIAG)
DOWN_RIGHT = ( _DIAG, -_DIAG)

ALL = (UP, DOWN, LEFT, RIGHT, UP_LEFT, UP_RIGHT, DOWN_LEFT, DOWN_RIGHT)
```

- [ ] **Step 2: Write tests**

```python
# tests/test_core_directions.py
import math, unittest
from expra_engine.core.directions import UP, DOWN, LEFT, RIGHT, UP_LEFT, ALL

class DirectionTests(unittest.TestCase):
    def test_up_is_unit_vector(self):
        self.assertAlmostEqual(math.hypot(*UP), 1.0)

    def test_all_are_unit_vectors(self):
        for d in ALL:
            self.assertAlmostEqual(math.hypot(*d), 1.0, places=6)

    def test_up_is_positive_y(self):
        self.assertEqual(UP, (0.0, 1.0))

    def test_down_is_negative_y(self):
        self.assertEqual(DOWN, (0.0, -1.0))
```

- [ ] **Step 3: Run and commit**

```bash
.venv/bin/python -m pytest tests/test_core_directions.py -v
git add src/expra_engine/core/directions.py tests/test_core_directions.py
git commit -m "feat: add core/directions — named unit-vector direction constants"
```

---

## Task 20 — Window placement persistence

**Source:** SA audit — `window_placement.py`.

**Files:**
- Create: `src/expra_engine/editor/window_placement.py`
- Modify: `src/expra_engine/ui/editor_window.py` (save on close, restore on open)
- Create: `tests/test_window_placement.py`

- [ ] **Step 1: Write pure-logic module**

```python
# src/expra_engine/editor/window_placement.py
"""Save and restore editor window geometry via PreferencesStore."""
from __future__ import annotations
from dataclasses import dataclass
import re


@dataclass
class WindowGeometry:
    width: int
    height: int
    x: int
    y: int

    def to_tk_geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"

    @classmethod
    def from_tk_geometry(cls, geometry: str) -> "WindowGeometry | None":
        m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geometry)
        if not m:
            return None
        return cls(int(m[1]), int(m[2]), int(m[3]), int(m[4]))
```

- [ ] **Step 2: Wire into EditorWindow**

In `editor_window.py`:
- On close: call `WindowGeometry.from_tk_geometry(self._root.geometry())` and save to preferences
- On init: read saved geometry, call `self._root.geometry(saved.to_tk_geometry())` if valid

- [ ] **Step 3: Write tests**

```python
# tests/test_window_placement.py
import unittest
from expra_engine.editor.window_placement import WindowGeometry

class WindowGeometryTests(unittest.TestCase):
    def test_round_trip(self):
        wg = WindowGeometry(1280, 800, 100, 50)
        s = wg.to_tk_geometry()
        wg2 = WindowGeometry.from_tk_geometry(s)
        self.assertEqual(wg, wg2)

    def test_invalid_string_returns_none(self):
        self.assertIsNone(WindowGeometry.from_tk_geometry("invalid"))

    def test_negative_position_ok(self):
        wg = WindowGeometry.from_tk_geometry("800x600+-10+-20")
        self.assertIsNotNone(wg)
        self.assertEqual(wg.x, -10)
        self.assertEqual(wg.y, -20)
```

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest tests/test_window_placement.py -v
git add src/expra_engine/editor/window_placement.py tests/test_window_placement.py
git commit -m "feat: add editor/window_placement — save/restore window geometry"
```

---

## Task 21 — PanelRouter tests (navigation.py gap)

**Source:** Internal audit — `PanelRouter` pure logic is untested.

**Files:**
- Create: `tests/test_navigation.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_navigation.py
import unittest
from unittest.mock import MagicMock
from expra_engine.ui.navigation import PanelRouter


class PanelRouterTests(unittest.TestCase):
    def test_register_and_show(self):
        r = PanelRouter()
        panel = MagicMock()
        r.register("scene", panel)
        r.show("scene")
        self.assertEqual(r.active_key, "scene")

    def test_show_unknown_raises(self):
        r = PanelRouter()
        with self.assertRaises((KeyError, ValueError)):
            r.show("nonexistent")

    def test_registered_keys(self):
        r = PanelRouter()
        r.register("a", MagicMock())
        r.register("b", MagicMock())
        self.assertIn("a", r.registered_keys)
        self.assertIn("b", r.registered_keys)

    def test_get_panel_returns_registered(self):
        r = PanelRouter()
        panel = MagicMock()
        r.register("x", panel)
        self.assertIs(r.get_panel("x"), panel)

    def test_initial_active_key_is_none_or_first(self):
        r = PanelRouter()
        # Before any show(), active_key should be None or a defined default
        self.assertIsNone(r.active_key)
```

- [ ] **Step 2: Run (fix any mismatched API calls)**

```bash
.venv/bin/python -m pytest tests/test_navigation.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_navigation.py
git commit -m "test: add PanelRouter tests for navigation.py"
```

---

## Task 22 — component_from_dict edge cases

**Source:** Internal audit — `register_component_type` / `component_from_dict` untested directly.

**Files:**
- Extend: `tests/test_entity.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_entity.py`:

```python
class ComponentRegistryTests(unittest.TestCase):
    def test_component_from_dict_known_type(self):
        from expra_engine.core.component import component_from_dict, TransformComponent
        d = {"component_type": "TransformComponent", "x": 1.0, "y": 2.0, "rotation": 0.0}
        c = component_from_dict(d)
        self.assertIsInstance(c, TransformComponent)
        self.assertAlmostEqual(c.x, 1.0)

    def test_component_from_dict_unknown_type_raises_or_returns_none(self):
        from expra_engine.core.component import component_from_dict
        # Should either raise a KeyError/ValueError, or return None — not silently succeed
        result = component_from_dict({"component_type": "__nonexistent__"})
        self.assertIsNone(result)  # adjust if implementation raises

    def test_register_custom_type(self):
        from expra_engine.core.component import (
            register_component_type, component_from_dict, Component
        )
        from dataclasses import dataclass

        @dataclass
        class TagComponent(Component):
            tag: str = ""
            def to_dict(self): return {"component_type": "TagComponent", "tag": self.tag}
            @classmethod
            def from_dict(cls, d): return cls(tag=d.get("tag", ""))

        register_component_type("TagComponent", TagComponent)
        c = component_from_dict({"component_type": "TagComponent", "tag": "player"})
        self.assertIsInstance(c, TagComponent)
        self.assertEqual(c.tag, "player")
```

- [ ] **Step 2: Run and fix if needed**

```bash
.venv/bin/python -m pytest tests/test_entity.py -v -k "ComponentRegistry"
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_entity.py
git commit -m "test: add component_from_dict and register_component_type edge cases"
```

---

## Task 23 — Grid2D paste negative-offset clip edge case

**Source:** Internal audit — `clip=True` with negative (x,y) offset not tested.

**Files:**
- Extend: `tests/test_core_grid2d.py`

- [ ] **Step 1: Add test**

```python
def test_paste_with_clip_negative_offset_skips_oob(self):
    """paste(src, -1, -1, clip=True) should not crash and should skip OOB cells."""
    dst = Grid2D(3, 3, default_factory=lambda: 0)
    src = Grid2D(2, 2, default_factory=lambda: 9)
    # Paste with negative offset — only (1,1) in src lands at (0,0) in dst
    dst.paste(src, -1, -1, clip=True)
    # Origin cell gets src[1,1]=9; cells not covered stay 0
    self.assertEqual(dst.get(0, 0), 9)
    self.assertEqual(dst.get(1, 0), 0)
    self.assertEqual(dst.get(0, 1), 0)
```

- [ ] **Step 2: Run**

```bash
.venv/bin/python -m pytest tests/test_core_grid2d.py -v -k "negative_offset"
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_core_grid2d.py
git commit -m "test: Grid2D paste with negative offset and clip=True"
```

---

## Task 24 — UICoordinator + AppCoordinator missing edge-case tests

**Source:** Internal audit (SA) — batch-depth, cancel-after-shutdown, concurrent-workers.

**Files:**
- Extend: `tests/test_ui_coordinator.py`
- Extend: `tests/test_app_coordinator.py`

- [ ] **Step 1: UICoordinator batch-depth tests**

Add to `tests/test_ui_coordinator.py`:

```python
def test_begin_batch_twice_end_once_stays_batching(self):
    """Nested batch: two begins, one end — should NOT flush yet."""
    ui = UICoordinator()
    renders = []
    ui.begin_batch()
    ui.begin_batch()
    ui.queue("k", lambda: renders.append(1))
    ui.end_batch()
    self.assertEqual(renders, [])  # still one begin pending

def test_end_batch_without_begin_is_noop(self):
    """end_batch before any begin must not raise."""
    ui = UICoordinator()
    ui.end_batch()  # should not raise

def test_flush_clears_all_pending(self):
    ui = UICoordinator()
    renders = []
    ui.begin_batch()
    ui.queue("a", lambda: renders.append("a"))
    ui.queue("b", lambda: renders.append("b"))
    ui.flush()
    self.assertEqual(sorted(renders), ["a", "b"])
```

- [ ] **Step 2: AppCoordinator concurrent + shutdown tests**

Add to `tests/test_app_coordinator.py`:

```python
def test_submit_after_shutdown_is_rejected(self):
    coord = AppCoordinator(deliver=ImmediateDelivery())
    coord.shutdown()
    with self.assertRaises((RuntimeError, ValueError)):
        coord.run("k", lambda cancel, emit: None)

def test_cancel_all_before_workers_finish(self):
    """cancel_all should not deadlock when workers are still running."""
    import threading
    started = threading.Event()
    blocker = threading.Event()

    def slow_task(cancel, emit):
        started.set()
        blocker.wait(timeout=2.0)
        return "done"

    coord = AppCoordinator(deliver=ImmediateDelivery())
    coord.run("k", slow_task)
    started.wait(timeout=1.0)
    coord.cancel_all()
    blocker.set()
    # Should return without deadlocking
```

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/test_ui_coordinator.py tests/test_app_coordinator.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_ui_coordinator.py tests/test_app_coordinator.py
git commit -m "test: UICoordinator batch-depth edge cases + AppCoordinator concurrent shutdown"
```

---

## Task 25 — clock time_scale > 1.0 fast-forward test

**Source:** Internal audit — fast-forward path (`time_scale > 1.0`) untested.

**Files:**
- Extend: `tests/test_runtime_clock_pause.py`

- [ ] **Step 1: Add test**

```python
def test_time_scale_greater_than_one_fast_forwards(self):
    """time_scale=2.0 should advance the simulation 2× faster than real time."""
    clock = RuntimeClock(fixed_step=1/60)
    clock.time_scale = 2.0
    updates = []
    clock.advance(1.0 / 60, lambda dt: updates.append(dt))
    # With time_scale=2 the effective step is 2× normal
    for dt in updates:
        self.assertAlmostEqual(dt, 2 / 60, places=5)

def test_time_scale_returns_to_normal(self):
    clock = RuntimeClock(fixed_step=1/60)
    clock.time_scale = 3.0
    clock.time_scale = 1.0
    updates = []
    clock.advance(1.0 / 60, lambda dt: updates.append(dt))
    for dt in updates:
        self.assertAlmostEqual(dt, 1 / 60, places=5)
```

- [ ] **Step 2: Run**

```bash
.venv/bin/python -m pytest tests/test_runtime_clock_pause.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_runtime_clock_pause.py
git commit -m "test: RuntimeClock time_scale > 1.0 fast-forward path"
```

---

## Task 26 — Autosave wiring + Recent Projects menu

**Source:** SA audit — `EditorPreferences.autosave_interval_ms` never started;
`recent_projects` never surfaced in File menu.

**Files:**
- Modify: `src/expra_engine/ui/editor_window.py`

- [ ] **Step 1: Wire autosave**

In `editor_window.py`, after `_create_default_scene()`:

```python
def _start_autosave(self) -> None:
    interval_ms = 30_000  # default; later from preferences
    def _autosave() -> None:
        self._act_save_scene_silent()
        if not self._is_closing:
            self._root.after(interval_ms, _autosave)
    self._root.after(interval_ms, _autosave)

def _act_save_scene_silent(self) -> None:
    """Auto-save to last used path; no dialog if path unknown."""
    # Only saves if a path was previously chosen; silent otherwise
    if hasattr(self, "_last_save_path") and self._last_save_path:
        import json
        scene = self._engine.edit_scene
        if scene:
            self._last_save_path.write_text(
                json.dumps(scene.to_dict(), indent=2), encoding="utf-8"
            )
```

Track `self._last_save_path: Path | None = None` in `__init__`, set it in `_act_save_scene`.

- [ ] **Step 2: Wire recent projects submenu**

In `_build_menubar()`, after `file_menu.add_command(label="Save Scene..."...)`:

```python
recent_menu = tk.Menu(file_menu, tearoff=0)
file_menu.add_cascade(label="Open Recent", menu=recent_menu)
# Populate from preferences (placeholder for now)
recent_menu.add_command(label="(none)", state="disabled")
self._recent_menu = recent_menu
```

- [ ] **Step 3: Run full test suite to verify no regression**

```bash
.venv/bin/python -m pytest tests/ --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add src/expra_engine/ui/editor_window.py
git commit -m "feat: wire autosave timer and Recent Projects stub in File menu"
```

---

## Task 27 — Final test run, version bump, wheel 0.1.10.0

- [ ] **Step 1: Run all tests**

```bash
cd /home/btn17/Downloads/expra-engine
.venv/bin/python -m pytest tests/ --tb=short -q
```

Expected: all pass (target ~960+ tests)

- [ ] **Step 2: Format + lint**

```bash
.venv/bin/ruff format src/ tests/
.venv/bin/ruff check src/ tests/ --fix
```

- [ ] **Step 3: Bump version**

```bash
sed -i 's/__version__ = "0.1.9.1"/__version__ = "0.1.10.0"/' \
    src/expra_engine/_version.py
```

- [ ] **Step 4: Build + checksum**

```bash
.venv/bin/python -m build --wheel
sha256sum dist/expra_engine-0.1.10.0-py3-none-any.whl > dist/SHA256SUMS
```

- [ ] **Step 5: Commit + push**

```bash
git add src/expra_engine/_version.py
git add -f dist/expra_engine-0.1.10.0-py3-none-any.whl dist/SHA256SUMS
git commit -m "build: publish wheel 0.1.10.0 — edge cases, easing, tween, sequence, platformer, bounds, math_utils, directions, layers, verify_export fix"
git push
```

---

## Full remaining gaps table (not in this plan — future work)

| Gap | Source | Effort | Notes |
|---|---|---|---|
| Sprite / SpriteSheetAnimation data model | Ursina | M | depends on Sequence |
| FrameAnimation boomerang loop mode | Ursina | M | extend AnimationClip |
| ParticleBurst data model | Ursina | M | pure data, no eval |
| ColorPicker ui_model | Ursina | M | Color HSV already done |
| DropdownMenu ui_model | Ursina | M | game-runtime UI |
| VecField safe multi-component input | Ursina | M | inspector numeric fields |
| invoke() / @after / @every | Ursina | S | runtime/invoke.py |
| Async asset loading system | ppb | L | WeakValueDict cache, background threads |
| Targeted event delivery | ppb | M | signal(event, targets=[...]) |
| Two-phase update/commit | ppb | S | stage_changes / on_commit |
| PreRender event | ppb | S | before-frame hook |
| BlendMode singletons + entity opacity | ppb | S | rendering effects |
| Scene.background_color + show_cursor | ppb | S | per-scene rendering settings |
| MouseButton typed singletons + delta | ppb | S | pointer system extension |
| Quitter/Failer test helpers | ppb | S | engine integration test quality |
| Loading screen base class | ppb | M | depends on asset system |
| Status/loading/error/empty-state widget | SA | S | reusable panel state widget |
| StatusBadge Tk widget | SA | S | styles declared, widget missing |
| Keyboard shortcut registry | SA | S–M | discoverable shortcuts |
| Search/filter Entry widget | SA | S | hierarchy + asset browser |
| Preferences UI / settings dialog | SA | M | UI for PreferencesStore |
| Asset Browser Tk panel | SA | M–L | data model exists; no widget |
| Canvas time-series graph | SA | L | frame-time, audio meters |
| Live-Tk test fixture | SA | M | shared setup/teardown |
| Shared RecordingWidget test double | SA | S | DRY fake widget |
| Wiring consistency test | SA | S–M | catch dispatch/register mismatches |
