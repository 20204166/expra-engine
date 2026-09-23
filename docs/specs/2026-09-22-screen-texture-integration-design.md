# Screen-Texture Integration Design

**Status:** Approved for implementation

**Goal:** Make BackBufferCopy a real ordered runtime operation by adding a
renderer-neutral screen-texture consumer and a Pygame capture/sampling backend,
without replacing Expra's existing scene, frame, renderer, or resource owners.

## Decision

Use an additive ordered-submission seam. `RenderFrame.items`, elapsed time,
payload, modulation, and all existing construction sites remain valid. A new
empty-default `submissions` field carries ordinary `RenderItem` values and
screen-effect markers only when a scene contains screen effects. The planner
turns that stream into one ordered `RenderPlan` before backend execution.

Rejected alternatives:

- Carrying plans in the legacy Pygame payload would couple neutral rendering to
  the legacy path.
- A second effect renderer would duplicate ordinary primitive, text, texture,
  and nine-slice drawing and violate canonical ownership.

## Ownership

- `Scene` and `Entity` retain hierarchy, component ownership, and serialization.
- `TransformComponent` and `TransformInterpolator` remain authoritative for
  simulation and sampled visual transforms.
- `RenderItem` and `RenderFrame.items` retain the ordinary draw contract.
- `render_extractor` remains the only Scene-to-render-data extraction path.
- `screen_texture.py` owns serialized component configuration, neutral requests,
  and effect markers. It owns no Pygame surfaces.
- `render_pipeline.py` owns deterministic operation planning and imports no
  Pygame code.
- `PygameRenderer` remains the ordinary draw owner.
- `pygame_screen_pipeline.py` owns copied surfaces, named capture lifetime,
  mipmaps, UV/filter sampling, tint/opacity, and sampled blits. It delegates
  `DrawItemOp` to `PygameRenderer` and is not a second renderer.
- `PygameRuntime` continues to own display and frame lifecycle.

The unintegrated duplicate `runtime/back_buffer_copy.py` is removed. Its test
coverage is migrated to the canonical `screen_texture.py` contracts rather than
maintaining two component types with the same serialized discriminator.

## Data Flow

1. Component registration exposes `BackBufferCopyComponent` and
   `ScreenTextureComponent`, including Inspector metadata.
2. `render_extractor` walks enabled entities and components in insertion order,
   resolves each effect transform through the existing transform path, and
   emits ordinary items plus effect markers into `RenderFrame.submissions`.
3. `RenderPlanBuilder.from_frame()` assigns stable ordering keys using phase,
   layer, world depth, and submission index. With no effects, ordinary item
   ordering remains the existing `RenderFrame` ordering.
4. The planner inserts automatic viewport capture before first use of an empty
   named slot, inserts mipmap generation only for the first mipmapped consumer,
   and resets slot mip state after explicit recapture.
5. `PygameRenderer` clears the target, executes the ordered plan through
   `PygameScreenPipeline`, and supplies its existing per-item draw logic as the
   `DrawItemOp` callback.

## Capture and Sampling Semantics

- RECT is local to the owning entity. The backend transforms four corners using
  the already-resolved world transform, projects through the active camera,
  clips to viewport and surface, and stores a non-mutating copy.
- VIEWPORT ignores the local rectangle and captures the active viewport.
- Explicit captures replace their named slot. Later draws do not mutate a
  snapshot; only a later capture replaces it.
- ScreenTexture samples the selected named slot using normalized UVs, world
  destination dimensions, nearest/linear filtering, optional mip level, LOD,
  tint, opacity, and transform/camera behavior.
- Captures are frame resources. They are cleared at frame start and on renderer
  start, stop, surface replacement, resize, and context reset. They never enter
  scene/component data.
- Canvas modulation is applied once to preceding ordinary draws. Sampled pixels
  are not modulated a second time; ScreenTexture tint and opacity apply to the
  new screen-texture draw.

## Compatibility Boundaries

- Existing `RenderFrame()` construction remains valid through defaults.
- Ordinary frames bypass the screen pipeline and retain existing Pygame draw
  behavior.
- The legacy tag-based `PygameRenderFrame` path does not resolve components or
  screen effects independently. The normal project runner carries canonical
  extractor submissions; legacy HUD behavior remains intact.
- The editor keeps ordinary Tk preview behavior. Its render target exposes
  screen effects as unsupported preview data instead of attempting fake pixel
  effects or coupling runtime support to Tk.
- The existing Pygame export stages the complete runtime directory. Export
  smoke coverage proves all three new runtime modules are included without
  adding editor dependencies.
- CanvasGroup remains out of scope because subtree boundaries and off-screen
  child composition are not implemented by this operation layer.

## Validation

The integration must preserve all supplied tests and add coverage for:

- component registration, Inspector metadata, malformed values, disabled
  entities/components, and full Scene JSON round trips;
- draw/capture/draw ordering, capture/screen/draw ordering, stable equal-key
  ordering, named slots, explicit versus automatic capture, and mip reuse and
  invalidation;
- local RECT transformation through translation, scale, rotation, parent and
  camera transforms, viewport clipping, nonzero viewport origin, and resize;
- copied rather than aliased surfaces, source immutability, UV/filter/mipmap
  sampling, LOD, tint, opacity, rotation, explicit unsupported errors, and
  cleanup;
- unchanged ordinary rendering, CanvasModulate, animation, interpolation,
  editor preview, legacy Pygame, export, and one end-to-end Scene-to-Pygame
  capture-at-the-correct-order test.

Validation order is focused screen tests, component/schema and extractor
tests, runtime/Pygame/editor/export regressions, full suite, compileall,
configured static checks, diff check, and meaningful source-line counts.

## Acceptance Criteria

The feature is complete only when BackBufferCopy has a real downstream
ScreenTexture consumer, no second renderer or shader compiler is introduced,
no backend surface or operation object is serialized, ordinary rendering stays
backward compatible, and every source capability in the integration brief is
classified as implemented, reused, adapted, deferred, or Godot/GPU-specific.
