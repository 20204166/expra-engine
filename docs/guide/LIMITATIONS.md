# Limitations

Honest current status. Classifications: **SUPPORTED**, **PARTIAL**, **NOT YET
SUPPORTED**, **EXPERIMENTAL**, **DEPRECATED**.

## World runtime

- Multi-Level Worlds, connectivity, streaming, persistent actors, transition
  modes — **SUPPORTED**.
- `TransitionMode.FADE` computes a fade `alpha` but does **not** render a fade
  itself (renderer responsibility) — **PARTIAL**.
- `TransitionMode.LOADING` behaves identically to `INSTANT` — **PARTIAL**.
- Streaming settings (`max_concurrent_loads`, `max_loaded_levels`) and
  `LevelDescriptor.always_loaded`/`priority` are in the data model but **not
  editable in the editor UI** — **PARTIAL**.

## World editor

- Add/remove/place Levels, set initial level, create connections — **SUPPORTED**.
- Editing streaming settings / always-loaded / priority via UI — **NOT YET
  SUPPORTED**.

## Rendering

- Pygame 2D primitives, sprites, text, 2D lighting, normal mapping, screen
  capture/texture — **SUPPORTED** (runtime).
- `blend_mode` (`add`/`multiply`) — declared in the data model but the Pygame
  renderer does **not** implement it (`RendererCapabilities.blend_mode=False`) —
  **NOT YET SUPPORTED**.
- Screen effects in the editor preview — reported as unsupported, not drawn —
  **PARTIAL** (runtime only).
- GPU/3D/perspective renderer — **NOT YET SUPPORTED** (Pygame CPU only).

## TileMap / navigation / 3D / 2.5D

- `tilemap.py` defines `TileCoordinate`/`TileData`/`TileMap` data types but no
  full tilemap renderer/editor — **PARTIAL**.
- 3D and isometric/2.5D — **NOT YET SUPPORTED**.

## UI

- Entity/component/scene-built HUDs and menus — **SUPPORTED**.
- A runtime layout/widget system (scroll view, focus, buttons/checkboxes,
  layouts) — **NOT YET SUPPORTED** (see `GAME_UI_FUTURE.md`).

## Audio

- 2D listener/stream contracts and mixing — **SUPPORTED** at the contract layer;
  actual backend playback depends on the attached runtime — **PARTIAL**.

## Navigation / save system / status effects / controller

- Navigation/pathfinding — **NOT YET SUPPORTED**.
- Full save-game framework — **NOT YET SUPPORTED** (use `UserDataStore` +
  World session state).
- Status-effect/attribute system — **NOT YET SUPPORTED** (build with behaviours).
- Gamepad/controller input — **NOT YET SUPPORTED** (no joystick events).

## Input

- Keyboard + mouse buttons — **SUPPORTED**.
- Analog axes, a "held" phase, mouse-motion-as-action — **NOT YET SUPPORTED**.

## Physics

- Overlap/raycast queries, triggers, area overrides — **SUPPORTED**.
- Rigid-body dynamics, collision response, broadphase — **NOT YET SUPPORTED**
  (by design: it's a query layer).

## Scene instances

- Nesting + cycle detection + overrides — **SUPPORTED**.
- Overrides are Phase 1 (first-name-match, script-only, no inheritance) —
  **PARTIAL**.

## Export / MCP

- Export (linux/windows, pygame/none, bytecode, verification) — **SUPPORTED**.
- MCP tooling — **SUPPORTED**, gated by trusted roots and network policy.

## Deprecated

- Legacy `.json` document import path — read-only; `save_document` writes `.pb`.
- `Project.save_scene` (legacy JSON writer), `Project.start_scene`/`entry_point`
  aliases — **DEPRECATED** (kept for compatibility).
- `Engine.update()` — legacy timing-only shim — **DEPRECATED**.
