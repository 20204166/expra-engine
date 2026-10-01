# UI

Game UI in Expra is built from the same primitives as gameplay: **Entities,
Components, Scenes, and Behaviours**. There is no separate widget runtime for
shipped games (the editor's Tk widgets are editor-only).

## Building blocks

- **`CameraMountComponent`** — optional viewport-space rendering for a HUD root and its resolved child hierarchy.
- **`TextComponent`** — labels.
- **`SpriteComponent` / `PrimitiveComponent`** — panels, backgrounds, icons,
  buttons (with `Centered`, `offset`, `layer`).
- **`AnimatedSprite2DComponent`** — animated UI elements.
- **`SceneInstanceComponent`** — reuse a HUD Scene across Levels.
- **`Behaviour`** — interaction logic and dynamic updates.

## HUD composition

A HUD is typically a Scene Instance in each Level that needs it, rather than
copied entities. Attach a `CameraMountComponent` to the instance root to make its
resolved visual hierarchy independent of camera motion:

```python
from expra_engine.runtime.camera_mount import CameraMountComponent

hud_root.add_component(CameraMountComponent(mount="top_left", x=16.0, y=-16.0))
```

`mount` accepts `top_left`, `top_center`, `top_right`, `center_left`, `center`,
`center_right`, `bottom_left`, `bottom_center`, or `bottom_right`. `x` is a
right-positive offset and `y` is an up-positive offset in logical viewport
pixels. A HUD layout unit is one pixel in the current viewport. On resize, the
named anchor follows its viewport edge/center; offsets and content sizes remain
fixed, with overflow clipped. There is no automatic reflow, proportional scale,
or safe-area inset.

The mount root's Transform is excluded from the mounted visual hierarchy and is
never rewritten. Its local children define render-space offsets. Physics and
collision continue to use normal World-space transforms. Without a mount
component, entities keep the existing World-space rendering behavior.

## Input and picking

There is no built-in UI picking/widget system. Handle interaction in Behaviours:
query colliders on UI entities with `PhysicsWorld2D.overlap`/`raycast`, or
translate mouse position with `camera.translate_to_game`. Keyboard/mouse input
comes through the `InputMap` (see [Input](INPUT.md)). Viewport-mounted visuals
currently have no built-in pointer picking or hit-test mapping; collider geometry
remains in World space.

## Examples

- **PlayerStatusHUD** — a Scene Instance with a health bar (primitives/sprite) driven by a
  Behaviour that reads player state.
- **DialogueHUD** — text entities + a `Behaviour` advancing through dialogue.
- **PauseMenu** — an overlay Scene with buttons, toggled by a Behaviour.
- **SkillTree** — nested mounted entities with colliders for picking in World space.

## What is NOT supported

There is no layout system, no scroll view, no focus/tab order, no built-in
button/checkbox/slider widgets in the runtime. A future renderer-backed game UI
package is described in `docs/GAME_UI_FUTURE.md` but is **not implemented**.
Build simple HUDs/menus from entities; for complex UI, expect to write the
layout and interaction yourself.
