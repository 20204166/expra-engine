# UI

Game UI in Expra is built from the same primitives as gameplay: **Entities,
Components, Scenes, and Behaviours**. There is no separate widget runtime for
shipped games (the editor's Tk widgets are editor-only).

## Building blocks

- **Screen-space entities** — entities placed in screen/camera space.
- **`TextComponent`** — labels.
- **`SpriteComponent` / `PrimitiveComponent`** — panels, backgrounds, icons,
  buttons (with `Centered`, `offset`, `layer`).
- **`AnimatedSprite2DComponent`** — animated UI elements.
- **`SceneInstanceComponent`** — reuse a HUD Scene across Levels.
- **`Behaviour`** — interaction logic and dynamic updates.

## HUD composition

A HUD is a Scene with screen-space entities. Instance it (via
`SceneInstanceComponent`) into Levels that need it, rather than copying entities
into every Level.

## Input and picking

There is no built-in UI picking/widget system. Handle interaction in Behaviours:
query colliders on UI entities with `PhysicsWorld2D.overlap`/`raycast`, or
translate mouse position with `camera.translate_to_game`. Keyboard/mouse input
comes through the `InputMap` (see [Input](INPUT.md)).

## Examples

- **PlayerStatusHUD** — a Scene with a health bar (primitives/sprite) driven by a
  Behaviour that reads player state.
- **DialogueHUD** — text entities + a `Behaviour` advancing through dialogue.
- **PauseMenu** — an overlay Scene with buttons, toggled by a Behaviour.
- **SkillTree** — nested screen-space entities with colliders for picking.

## What is NOT supported

There is no layout system, no scroll view, no focus/tab order, no built-in
button/checkbox/slider widgets in the runtime. A future renderer-backed game UI
package is described in `docs/GAME_UI_FUTURE.md` but is **not implemented**.
Build simple HUDs/menus from entities; for complex UI, expect to write the
layout and interaction yourself.
