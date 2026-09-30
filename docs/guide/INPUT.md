# Input

Input is semantic: scripts consume actions (e.g. `move_right`), never platform
key names.

## Model

```python
@dataclass(frozen=True)
class PhysicalInput:
    device: str               # lowercased, e.g. "keyboard", "mouse"
    control: str              # lowercased, e.g. "left", "button-1"
    modifiers: frozenset[str]

@dataclass(frozen=True)
class ActionEvent:
    action: ActionId          # semantic action name
    phase: str                # "pressed" or "released"
    physical: PhysicalInput
```

## InputMap

```python
input_map.bind(ActionId("move_left"), PhysicalInput("keyboard", "left"))
input_map.press(PhysicalInput("keyboard", "left"))    # -> ("pressed", ...)
input_map.release(PhysicalInput("keyboard", "left"))  # -> ("released", ...)
input_map.is_held("move_left")
input_map.held_actions
input_map.focus_lost()                                 # release all, deterministically
```

Bindings reject duplicate physical-control mappings. `Project.set_input_binding`
persists bindings into `project.json`.

## Supported devices

| Device | Controls | Notes |
|---|---|---|
| Keyboard | key names (`pygame.key.name`) | press/release |
| Mouse | `button-<n>` | buttons only |
| Gamepad | `button-<n>` (buttons), `axis-<n>` (axes) | buttons press/release; axes via `axis_value` |

Analog axes are bound separately from digital buttons:

```python
input_map.bind_axis(ActionId("move_x"), PhysicalInput("gamepad", "axis-0"), deadzone=0.2)
input_map.set_axis(PhysicalInput("gamepad", "axis-0"), 0.5)  # deadzone-applied
input_map.axis_value("move_x")                                 # -> 0.375
```

All gamepads converge on the single `gamepad` device identity; per-device
disambiguation is not represented.

## What is NOT supported

- **Gamepad hats / device add-remove events** — only buttons and axes are
  consumed.
- **A \"held\" phase** — there is no held state in `ActionEvent`; use
  `is_held`.
- **Mouse motion as an action** — motion goes to UI, not through the input map.

## Behaviour access

In a `Behaviour`, `self.input.is_held(action)` reads held state, and
`on_input(event, signal)` receives `ActionEvent`s. Return `HANDLED` to consume.

## Editor vs runtime

The editor's own widgets (viewport pan/zoom, panel keyboard) are editor input,
separate from the game `InputMap`. In Play mode, the runtime `InputMap` drives
behaviours via the Pygame event loop.
