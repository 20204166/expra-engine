# Future Game UI Layer

## Boundary

The editor UI and a shipped game's UI are separate systems. The editor may use
`tkinter`, `ttk`, and `ttkbootstrap`; game code and exported games must not
depend on any of them. `expra_engine.design` is the shared, renderer-neutral
design vocabulary. It contains semantic values only and has no GUI imports.

The current editor adapter is `expra_engine.ui.styles`. It translates the
shared vocabulary into ttk styles and may add editor-only widget details.
Nothing in `core/`, `runtime/`, or a future game UI package should import that
adapter.

## Future Renderer-Backed API

When runtime UI is implemented, it should be a separate package with an
explicit renderer/context boundary. A possible initial surface is:

```text
GameCanvas
  UIElement
    Panel
    Label
    Button
    Image
    ProgressBar
    ScrollView
  AnchorLayout
  Row / Column / Stack
```

These are conceptual roles, not an implementation commitment. Elements should
own layout intent, semantic style state, input behavior, and children; the
renderer should own drawing, text shaping, texture upload, clipping, and
platform input translation. A game UI tree must be renderable by more than one
backend without changing game-facing layout code.

## Design Contracts

- **Tokens:** use semantic colors, typography roles, spacing scale, panel
  hierarchy, control metrics, and interaction states from `design.tokens`.
- **Layout:** support anchor, row, column, and stack composition with measured
  minimum/preferred sizes rather than fixed editor pixels.
- **Scaling:** apply DPI scale and a density scale before rasterization; keep
  logical coordinates independent of window pixels.
- **Responsive behavior:** resolve safe areas, minimum content width, aspect
  ratio changes, and fullscreen/windowed size changes during layout.
- **States:** represent default, hover, selected, focused, and disabled as
  semantic state, then let the backend choose its visual treatment.
- **Rendering:** expose draw/layout commands or a renderer protocol, never Tk
  widgets, so HUDs, pause menus, inventories, dialogue, quest logs, and touch
  controls can share the same scene-independent UI tree.

## Historical Editor Scope

The original editor-polish pass established the boundary and shared vocabulary.
The current additive foundation now includes renderer-neutral geometry,
nine-slice data, control state, focus/pointer contracts, runtime input,
timelines, animation, follow, tilemap, dialogue, and editor asset-scan
contracts. It still does not add `GameCanvas`, runtime widgets, a renderer, or
export integration.

## Runtime Contract Status

The approved runtime foundations are pure data/contracts in
`runtime/input.py`, `runtime/timeline.py`, `runtime/animation.py`,
`runtime/follow.py`, `runtime/tilemap.py`, and `runtime/dialogue.py`.
`editor/assets.py` is an editor-side async asset scan contract owned by the
existing `AppCoordinator` and `TkDeliveryQueue`; it is not game UI runtime.
Bounded numeric parsing is canonical in `core/safe_expression.py`, with
`editor/safe_expression.py` serving only as the editor re-export boundary.

There is no Panda/Ursina/Tk game runtime. Renderer implementation, dialogue
presentation, color/gradient editing, radial menus, grid editor behavior,
mobile touch translation, and platform display/window handling remain deferred
behind explicit renderer or platform seams.

## Audited Contract Direction

The audit in `docs/URSINA_INTEGRATION_MAP.md` confirms that the next smallest
renderer-neutral foundations are logical geometry, safe-area and
reference-resolution layout, nine-slice patch data, pure control state, focus,
and pointer contracts. These are data/runtime concerns, not Tk widgets or
Panda3D objects. Existing `Engine`/`Entity`/`Component` and coordinator owners
remain unchanged; window/display settings belong behind a future platform
backend, and a game runtime must never import the Tk editor path.
