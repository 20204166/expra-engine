# Non-Tk Playable Game Design

## Goal

Deliver a genuinely playable, graphical Expra game that can be launched from
an exported build without Tkinter, ttkbootstrap, the editor, Ursina, or Panda3D.
The first game is a small Neon Arena vertical slice used to expose missing
engine capabilities.

## Reference Decisions

- Ursina's contribution is the export shape: target runtime, dependency
  resolution, asset copying, bytecode/source staging, and launchers.
- PPB's contribution is the runtime shape: event-driven systems attached to a
  renderer-neutral engine loop.
- MiniPyEngine's contribution is the platform shape: Pygame/SDL window,
  keyboard events, and frame presentation.

## Runtime Architecture

`Engine` remains renderer-neutral and continues to own scenes, entities,
runtime state, events, clocks, and systems. A new Pygame runtime adapter owns
the process-facing concerns:

- create and destroy the Pygame window;
- poll SDL/Pygame events and expose keyboard/quit state;
- drive `Engine.tick(dt)` at the configured frame rate;
- present each rendered frame;
- stop cleanly on quit or window close.

A renderer system subscribes to existing runtime events. It draws the minimal
2D vocabulary needed by the sample game from scene entities and components.
The adapter is explicit in the game entry point and is not constructed by
`Engine`.

### Renderer Protocol

The runtime exposes a backend-neutral renderer contract for 2D games. Its
context contains immutable viewport/configuration data; its frame contains the
active scene, elapsed time, and optional game-facing HUD payload. The lifecycle
is explicit: `start(context)`, `render(frame)`, `resize(size)`, and `stop()`.
Renderers report capabilities such as primitive drawing, text, resizing, and
headless operation. The protocol contains no Pygame, Tk, SDL, Ursina, or
Panda3D types. `PygameRenderer` remains the first adapter and translates this
contract into Pygame draw calls.

The runtime loop owns timing, input, and presentation boundaries; it invokes
the renderer but never inspects its implementation. Renderer failures are
reported to the runtime and always trigger cleanup. A recording renderer and
dummy-SDL adapter provide deterministic tests for lifecycle ordering, repeated
frames, resize, headless operation, and failure cleanup.

### 3D Principles Applied To 2D

The contract is founded on graphics principles that improve the 2D path now:

- an orthographic camera with explicit view, projection, and viewport mapping;
- a depth value derived from render layer, with stable ordering for ties;
- parent-to-world transform composition before projection;
- viewport clipping/culling before backend draw calls;
- render phases and primitive descriptors that leave room for batching;
- a shared color/material description rather than backend-specific colors.

The first implementation remains primitive-only and orthographic. It does not
add meshes, lighting, perspective, or a 3D asset format. Those can consume the
same camera, transform, phase, and capability contracts later.

## Neon Arena Scope

The sample game will contain:

- a player controlled by WASD/arrow keys;
- a bounded arena;
- collectible targets and collision checks;
- score and elapsed-time HUD;
- a win state after all targets are collected;
- restart input after win;
- a visible renderer and a real frame loop.

The first renderer may use primitive shapes and text. It does not need a
general sprite/material system, audio, physics engine, or scene editor support
for this slice.

## Export Architecture

The export pipeline will gain a runtime dependency profile for the game:

- install the selected runtime package set, including Pygame, for the target;
- exclude editor-only packages and forbidden modules;
- include the runtime engine modules required by the game's entry point;
- preserve asset manifests and launcher generation;
- verify that the exported bundle has no Tk/editor/Ursina/Panda3D imports;
- execute a smoke-test entry point against the exported runtime where the host
  supports the target backend.

The Linux path is the first end-to-end target. Windows launcher/package
behavior remains covered by existing packager tests and static verification.

## Failure and State Handling

- Window close and `Quit` transition the engine to EDIT/terminated runtime
  state and release Pygame resources.
- Restart resets the runtime scene from the edit scene rather than mutating
  the saved scene.
- Missing display/backend or missing runtime dependency produces a clear
  launcher error and non-zero exit status.
- Export remains atomic: failed verification does not replace a previous
  build.

## Testing

Test-first coverage will include:

- input mapping and quit handling through injected Pygame events;
- renderer/system behavior using a fake or headless Pygame surface;
- Neon Arena movement, collection, win, and restart behavior;
- runtime loop lifecycle and cleanup;
- export dependency/profile selection;
- forbidden editor/Tk/Ursina/Panda3D import checks;
- a Linux exported-build smoke test that starts the game in a dummy video
  backend and reaches a deterministic completion signal.

## Non-Goals

- no Tkinter game runtime;
- no Ursina/Panda3D embedding;
- no general-purpose 3D renderer;
- no single-file executable;
- no macOS export in this slice;
- no editor project-management redesign.
