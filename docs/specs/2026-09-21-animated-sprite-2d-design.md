# AnimatedSprite2D Integration Design

**Goal:** Integrate the supplied renderer-neutral AnimatedSprite2D capability
into Expra's existing component, runtime, scene, extraction, and Pygame paths
without introducing parallel engine infrastructure.

## Architecture

`AnimatedSprite2DComponent` remains serialized configuration. A built-in
`RuntimeSystem` owns one transient `AnimatedSpritePlayer2D` per active runtime
entity/component and advances it from canonical `Update` events. Scene
transitions and runtime stop reconcile or clear that map; player state is never
written into scene data.

`extract_render_frame()` remains the only scene-to-render conversion path. It
accepts an optional runtime-player mapping and turns the player's
`SpriteFrameView` into the existing `RenderItem` contract. The contract gains
only sprite-neutral source-region, offset, centering, and flip fields. Existing
`SpriteComponent` extraction uses defaults, so its behavior remains unchanged.

`PygameRenderer` remains the backend owner. It resolves the existing texture
resource ID, applies the optional atlas region, visual offset/centering, and
flip operations, then blits the result. No Pygame dependency enters the
AnimatedSprite2D module.

## Registration And Serialization

The existing component registry imports and registers `AnimatedSprite2DComponent`
under `animated_sprite`, with metadata for its editable scalar and visual
properties. Nested `SpriteFrames2D` data round-trips through the existing
Entity/Scene JSON path. Runtime player state is deliberately absent from
`to_dict()` output.

## Timing And Events

The player remains the sole owner of AnimatedSprite2D playback semantics,
including weighted durations, reverse playback, loop modes, large deltas, and
event ordering. The runtime system only starts, advances, and reconciles
players. Events are exposed through the supplied `SpriteEvent2D` vocabulary;
the runtime system records/delivers them through its integration seam without
creating a second global signal queue.

## Validation

Tests cover the supplied player behavior plus registration, Inspector metadata,
component and Scene JSON round-trips, runtime lifecycle and stale-state
cleanup, renderer-neutral extraction, atlas/offset/centering/flips, tint
compatibility, Pygame rendering, and end-to-end scene-to-renderer behavior.
Existing animation, SpriteComponent, scene, runtime, and renderer tests must
continue to pass.
