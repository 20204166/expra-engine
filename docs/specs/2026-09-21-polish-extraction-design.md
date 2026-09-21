# Space Pong Polish Extraction Design

**Status:** Approved design; implementation pending the parity-map review.

## Goal

Make Expra capable of building one polished small 2D game through its real
editor and exported runtime, using proven behavior from the four reference
engines without importing their global scene graphs, loops, renderer objects,
Tk widgets, or unsafe loaders.

Space Pong is acceptance evidence, not an engine special case. No engine code
may branch on the project name, entity names, or Pong-specific gameplay.

## Existing Strengths

Expra already owns the core boundaries that must remain authoritative:

- `Engine`, `Project`, `Scene`, `Entity`, and `Component` own game data.
- `EventQueue`, `RuntimeClock`, `BehaviourSystem`, `Timeline`, `Tween`, and
  animation contracts own execution and time.
- `Renderer`, `RenderFrame`, `RenderItem`, camera, color, material, and
  primitive contracts are backend-neutral.
- `Input`, pointer/focus models, nine-slice geometry, editor contributions,
  `CommandStack`, and project/export workflows already have tests.
- Tk remains editor-only; Pygame remains a renderer/platform adapter.

The work therefore fills integration seams rather than replacing those owners.

## Architecture

### Authoring

Registered component types gain optional immutable field metadata. The Inspector
uses that metadata to construct typed controls and emits edits through the
existing editor command boundary. Add/remove component actions use the registry,
reject duplicates, preserve required-component policy, and are safe when the
selection changes or the entity disappears. Serialization remains each
component's canonical `to_dict`/`from_dict` contract.

### Shared rendering

One extraction path converts scene components into `RenderFrame` data:

```text
Scene + Components -> RenderExtractor -> RenderFrame -> Renderer adapter
```

The Tk viewport and Pygame renderer consume the same extracted component data,
but remain separate adapters. Editor selection, grid, collider outlines, and
gizmos are overlays, not runtime renderer behavior.

### Runtime UI

A pure runtime UI tree owns layout intent, semantic states, children, focus,
pointer capture, and actions. Existing geometry, anchors, focus, pointer,
control-state, and nine-slice models remain the source of truth. A Pygame
adapter owns text rasterization, texture resources, clipping, and draw calls.
The UI tree must not import Tk or Pygame.

### Physics and visual effects

Collider data and a deterministic 2D query backend fit behind the existing
`HitResult2D` and `TriggerEvent` contracts. Renderer-neutral materials support
only justified fields such as tint, opacity, outline, layered glow-like
primitives, and nine-slice descriptors. Tween/timeline drive feedback; Pong
scripts choose the colors, timings, and game content.

## Staged Implementation

1. Generic component metadata, Inspector add/remove/edit, stale-selection safety,
   command undo/redo, serialization, and focused tests.
2. Primitive/sprite/text/collider data plus shared render extraction and
   Pygame/Tk adapter parity.
3. Runtime UI tree, measurement, anchors/safe-area layout, text, panels,
   buttons, focus, pointer routing, resize, and nine-slice drawing.
4. Deterministic collider backend, editor collider preview, camera pan/zoom,
   frame selection, and preview overlays.
5. Space Pong construction through the editor, export/standalone validation,
   screenshots, parity-map updates, and final report.

Each stage is test-first, independently runnable, and keeps the prior runtime
and serialized project behavior backward compatible.

## Explicit Non-Goals

- No Ursina entity hierarchy, Panda3D coupling, PPB engine, or second event loop.
- No `PhysicsSystem2`; the existing physics contracts remain the boundary.
- No hardcoded Space Pong renderer/HUD/collision paths.
- No serialized Pygame surfaces, rectangles, vectors, font objects, or Tk data.
- No direct code reuse from the unlicensed System Analyzer checkout.
- No unsafe `eval`/`exec` asset loading or global camera/audio/scene state.
