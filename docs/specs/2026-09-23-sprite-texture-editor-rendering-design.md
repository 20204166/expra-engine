# Sprite/Texture Editor Rendering Design

**Goal:** Make Expra's Edit and Play views consume the same real sprite/texture
rendering semantics while preserving renderer-neutral scene data and the current
Tk editor interaction model.

## Source-Driven Capability Map

| Godot source behavior | Expra owner | Decision |
| --- | --- | --- |
| `Sprite2D::_get_rects()` computes source/destination rectangles, centering, offset, frames, and flips | `RenderItem`, `MaterialDescriptor`, `PygameRenderer._draw_contract_item()` | Reuse existing contract; add missing static-sprite fields |
| `Sprite2D::is_pixel_opaque()` maps a click through the inverse transform and samples alpha | `ViewportPanel._on_click()` currently uses bounds | Keep bounds selection in this slice; leave alpha hit testing for a later focused change |
| `AnimatedSprite2D` delegates frame texture/region and playback state | `AnimatedSpritePlayer2D.view`, `extract_render_frame()` | Reuse; do not duplicate animation state |
| `CanvasItemEditor::_draw_viewport()` renders the edited `SubViewport` before grid/gizmo/plugin overlays | `ViewportPanel._redraw()` | Add an offscreen runtime-pixel layer, retain Tk overlays |
| `EditorResourcePreview` and texture importers cache previews asynchronously | `editor/assets.py`, `ResourceService` | Keep asset IDs/scanning; defer thumbnail scheduling and full region UI |

## Architecture

`SpriteComponent` gains additive region, offset, centering, and flip fields. The
extractor maps them into the existing `RenderItem` fields; animated sprites keep
their transient `AnimatedSpritePlayer2D` owner and already use the same fields.

`PygameRenderer` remains the only texture draw owner. It gains an opt-in
transparent-clear mode so `ViewportPanel` can render a frame to an offscreen
Pygame surface, encode it as a Tk `PhotoImage`, and place it below editor
overlays. The existing `PygameResourceProvider` and project `ResourceService`
remain the resource/cache boundary. Missing Pygame or assets falls back to the
current Tk geometry path without changing scene data.

## Editor Lifecycle

`EditorWindow` supplies one project `ResourceService` to `ViewportPanel` and
replaces it when projects open or close. The viewport lazily creates the optional
Pygame surface/renderer, recreates it on size changes, and retains the Tk image
reference. Grid, selection, labels, colliders, entity markers, input, and camera
state remain Tk-owned. Runtime plans, surfaces, and preview images are never
serialized.

## Validation

Tests cover static-sprite serialization/extraction, cached texture loading,
source-region/flip rendering, transparent editor rendering/fallback behavior,
project resource-service lifecycle, existing animation behavior, and the full
focused renderer/editor suite. The full suite and Xvfb UI suite remain required;
Pygame-dependent pixel acceptance is reported separately when the optional
dependency is unavailable.
