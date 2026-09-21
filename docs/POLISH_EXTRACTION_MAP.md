# Polish / Multi-Engine Extraction Map

**Audit date:** 2026-09-21

This map records repository evidence before implementation. `A` means Expra is
already sufficient. `B` means adapt a source behavior. `C` means combine
source behavior with existing Expra contracts. `D` means add a missing seam
using source contracts. `E` means reject the source mechanism while retaining
useful behavior or test intent.

## Reference and License Boundary

| Source | Evidence | License/provenance decision |
|---|---|---|
| System Analyzer (`/home/btn17/Downloads/exp`) | `maintenance/ui/layout.py`, `render_coordinator.py`, `action_coordinator.py`, `tests/test_ui_primitives.py`, `tests/test_render_coordinator.py`, `tests/test_live_tk_resize.py` | Checkout declares `UNLICENSED`; behavior and test intent only, no code copying. |
| Ursina (`/home/btn17/Downloads/ursina-master`) | `ursina/prefabs/button.py`, `text.py`, `prefabs/window_panel.py`, `models/procedural/nine_slice.py`, `editor/level_editor.py`, `raycast.py`, `sequence.py` | MIT; adapt decoupled behavior and test intent, retain attribution if code is substantially reused. |
| PPB (`/home/btn17/Downloads/pursuedpybear-canon`) | `src/ppb/engine.py`, `camera.py`, `sprites.py`, `systems/renderer.py`, `assetlib.py`, `systems/clocks.py`, `tests/test_camera.py`, `tests/test_assets.py` | Artistic License 2.0; preserve test intent/contracts and record any substantial adaptation. |
| MiniPyEngine (`/home/btn17/Downloads/MiniPyEngine-main`) | `Engine/objects/GameObjectBase.py`, `GameObjects.py`, `GMMKR.py`, `maths/Material.py`, `StartGame.py` | MIT; use narrowly. Bundled asset rights are not established, so do not copy assets. |

## Capability Parity

| Capability | Current Expra state | Analyzer | Ursina | PPB | MiniPyEngine | Chosen owner/classification |
|---|---|---|---|---|---|---|
| Inspector/property editing | Transform and script fields; other components display read-only | Typed controls, validation, refresh | Level Inspector patterns | Component data contracts | Map object fields | `InspectorPanel` + registry metadata, B |
| Add/remove components | Add menu exists; no generic remove or field schema | Stable actions and stale delivery | Add/remove editor patterns | Object lifecycle | Append-only map editor | `ComponentRegistry` + `CommandStack`, D |
| Stale selection/action safety | Coordinator and editor command seams exist | Strongest reference | Editor has global-state caveats | Targeted event caveats | No tests | Existing coordinators + tests, A/B |
| Primitive visuals | Renderer primitives exist outside scene components | N/A | Quad/entity primitives | Shape assets | SimpleCube primitives | `PrimitiveComponent` + extractor, C |
| Sprite visuals/assets | Resource service exists; no scene visual component | N/A | Sprite/PPU/aspect behavior | Sprite/image lifecycle | Textured objects | `SpriteComponent` + asset adapter, C |
| Text | Pygame sample HUD only | Widget measurement/state patterns | `Text` wrapping/alignment | Text asset/font lifecycle | Menu text only | `TextComponent` + renderer text command, C |
| Nine-slice | Pure geometry model and tests | Panel layout patterns | `NineSlice` geometry | N/A | N/A | Existing nine-slice owner + draw adapter, C |
| Runtime panels/buttons | Control state models only; no render tree | Action/state patterns | Button/window/pause semantics | N/A | Menu buttons | Runtime UI tree + Pygame adapter, C |
| Layout/anchors/resize | Geometry contracts, no runtime tree | Resize/hysteresis patterns | Origins/grid layout | Camera scaling | Resolution menu | Runtime layout resolver, C |
| Focus/pointer | Pure models and pointer contracts | Lifecycle safety | Hover/pressed/focus behavior | Input event contracts | Mouse menu | Runtime UI input router, C |
| Collision configuration | Hit/trigger vocabulary only | N/A | Collider/raycast/hit result | No general collision | Weak AABB | `ColliderComponent` + deterministic backend, D/E |
| Physics edge cases | No solver/backend | N/A | Raycast semantics | Camera/geometry tests | Collision defects | Expra tests informed by contracts, D/E |
| Materials/colors | Color and opacity only | Semantic styling | Color/gradient helpers | Tint/opacity/blend | Material container | Extend `MaterialDescriptor` minimally, C |
| Animation/tween feedback | Pure runtime contracts already exist | Transition lifecycle | Sequence/curves/animator | Fixed/update timing | No animation system | Existing timeline/tween/animation, A/B |
| Particles/trails | Trail contract exists; no particle renderer | N/A | Trail/particle behavior | N/A | No particles | Defer; use layered primitives for Pong, E |
| Editor viewport | Tk markers/grid/selection; not runtime visuals | Real-widget resize evidence | Editor camera/gizmos | Camera math | Tk map editor | Shared extraction + Tk overlays, C |
| Camera/pan/zoom/frame | Camera projection exists; viewport controls incomplete | Resize patterns | EditorCamera controls | Camera round-trip tests | Camera math | Existing camera + editor adapter, C |
| Assets/project workflow | Strong logical IDs, mounts, export | N/A | Asset folder conventions | Cache/lifecycle contracts | CWD-based paths | Existing resource/export owners, A/C |
| Pause/win/game flow | Behaviour/runtime lifecycle exists; no runtime UI | Lifecycle/action patterns | Pause/menu patterns | Scene transitions | Menu state | Project scripts + runtime UI, C |

## Test Extraction Plan

| Area | Source test intent | New Expra regression tests |
|---|---|---|
| Inspector | Analyzer invalid values, refresh suppression, stale node delivery | Stale selected entity, removed component, invalid property type, undo/redo, duplicate add |
| Runtime UI | Ursina state transitions and PPB camera/asset edge cases | Resize/extreme aspect, hidden UI, destroyed focus target, rapid text changes, safe-area anchors |
| Rendering | PPB layer/order/visibility and camera round trips | Off-screen/partial primitives, zero-size rejection, alpha, deterministic equal-depth order |
| Collision | Ursina hit result fields and Expra trigger vocabulary | Exact contact, initial overlap, disabled/removed collider, trigger enter/stay/exit, deterministic order |
| Preview | Analyzer real resize/lifecycle and Ursina editor controls | Removed selection, malformed visual component, collider outline, pan/zoom/frame selection |

## Implementation Record

This section records the completed staged patches with:

- source file and symbol;
- behavior and edge cases preserved;
- coupling removed;
- Expra destination;
- adapted source tests and new regression tests;
- license/provenance status;
- rendered evidence and Space Pong result.

No reference implementation has been copied into Expra. The source repositories
were used for architecture and test-intent comparison only.

### Task 1: Component Metadata and Generic Inspector Authoring

- **Source symbols and destination:** System Analyzer `maintenance/ui/layout.py`
  and `action_coordinator.py` informed stale-delivery and edit-refresh concerns;
  Expra destinations are `PropertyDescriptor.convert`,
  `ComponentTypeSpec`, `registered_component_specs` in
  `core/component_schema.py`, `register_component_type` metadata in
  `core/component.py`, `CommandStack`/`SetComponentPropertyCommand`/
  `AddComponentCommand`/`RemoveComponentCommand` in `editor/commands.py`, and
  `InspectorPanel` metadata controls in `ui/inspector.py`.
- **Behavior preserved:** Typed float/int/bool/enum/color conversion rejects
  invalid and non-finite input without silent clamping; immutable metadata,
  required-component protection, duplicate rejection, stale target no-op, and
  undo/redo are preserved while existing component JSON and registry behavior
  remain compatible.
- **Coupling removed:** Inspector editing resolves the entity/component again
  at command execution rather than retaining a Tk selection or widget as the
  mutation target; field metadata is engine data, not control-specific code.
- **Expra destination:** Generic registry metadata and command-backed inspector
  authoring; no source-engine coordinator or widget was imported.
- **Tests:** `tests/test_component_schema.py` (conversion, rejection,
  immutability, required types, registry compatibility),
  `tests/test_editor_commands.py` (add/remove/property undo-redo and stale
  targets), and `tests/test_editor_ui.py` (inspector conversion) are the new or
  adapted Expra coverage; real Tk coverage also ran in the xvfb suite.
- **License/provenance:** System Analyzer checkout declares `UNLICENSED`;
  behavior and test intent only, no code copied or adapted. No third-party
  license notice is required for this implementation.
- **Evidence:** Commit `cc38d88`; focused tests and full suite passed. The
  Space Pong editor evidence changed script and collider values, undid them,
  and restored the scene (`docs/SPACE_PONG_FINAL_REPORT.md`).

### Task 2: Renderer-Neutral Visual Components and Extraction

- **Source symbols and destination:** PPB `systems/renderer.py`, `sprites.py`,
  and `tests/test_camera.py` informed renderer-neutral ordering and camera/test
  intent; Expra destinations are `PrimitiveComponent`, `SpriteComponent`,
  `TextComponent` in `runtime/visual_components.py`, `extract_render_frame`
  plus `_transform`/`_item` in `runtime/render_extractor.py`, and the existing
  `RenderItem`/`RenderFrame` contracts in `runtime/rendering.py`.
- **Behavior preserved:** JSON round-tripping, component enabled/visible gates,
  transform hierarchy composition, phase/layer ordering, stable entity order,
  and deterministic skipping of malformed visuals.
- **Coupling removed:** Scene visuals contain only finite scalar data, Expra
  colors, and asset/text identifiers; no Tk/Pygame objects enter serialization
  or extraction.
- **Tests:** `tests/test_render_extractor.py` covers round-trip payloads,
  metadata, finite values, transform composition, ordering, visibility, and
  malformed data; existing component/entity/scene suites cover compatibility.
  No reference implementation was copied; license status is therefore not
  applicable.
- **Evidence:** Commit `f49f8d7`; focused extraction/rendering tests passed and
  the Space Pong scene renders through this extractor without project-name
  branches.

### Task 3: Text, Materials, Nine-Slice, and Pygame Draw Adapter

- **Source symbols and destination:** Ursina `text.py`,
  `models/procedural/nine_slice.py`, and `prefabs/window_panel.py` informed
  text/panel behavior; Expra destinations are existing `MaterialDescriptor`,
  `RenderItem`,
  `ui_model.nine_slice.NineSlice.resolve`; additive `TextDescriptor` and
  `NineSliceDescriptor` in `runtime/rendering.py`, with translation in
  `runtime/pygame_renderer.py`.
- **Behavior preserved:** Legacy `RenderItem`/`RenderFrame` constructor
  signatures and tag-based `PygameRenderer.on_render` behavior; equal-depth
  ordering and existing nine-slice geometry remain unchanged.
- **Coupling removed:** Text measurement/font lookup and texture lookup use
  injected providers; descriptors contain no Pygame or Tk values. The adapter
  consumes resolved nine-slice rectangles rather than reimplementing geometry.
- **Tests:** `tests/test_runtime_rendering.py`, `tests/test_pygame_renderer.py`,
  `tests/test_render_extractor.py`, and `tests/test_ui_model_nine_slice.py`.
  No reference implementation was copied; license status is not applicable.
- **Evidence:** Commits `fab3fd0` and `2d2d9da`; renderer contracts, text,
  nine-slice, alpha, layer, and unsupported-blend reporting tests passed.

### Task 4: Runtime UI Tree, Layout, and Interaction

- **Source symbols and destination:** Ursina `prefabs/button.py`, `text.py`,
  and `prefabs/window_panel.py`, plus PPB `camera.py` and `tests/test_camera.py`,
  informed state/layout intent; Expra destinations are
  `runtime.ui.elements.UIElement`, `GameCanvas`, `Panel`, `Label`, `Button`,
  `runtime.ui.layout.LayoutSpec`/`LayoutResult`, `runtime.ui.events.UIEvent`,
  `PygameRenderer.draw_ui_commands`, and `PygameRuntime` input/resize routing.
- **Behavior preserved:** normalized anchors, safe-area/reference-resolution
  scaling, minimum/preferred sizing, deterministic z/order hit testing, control
  visual states, focus invalidation, pointer capture, modal/focused ownership,
  renderer-neutral draw commands, multiline wrapping, and nine-slice destination
  plus source patch mapping.
- **Coupling removed:** runtime UI models import neither Tk nor Pygame; Pygame
  receives injected modules/surfaces/fonts/resources and gameplay input is
  signalled only after UI dispatch declines ownership. Nine-slice mapping consumes
  `NineSlice.resolve()` results and does not duplicate its geometry algorithm.
- **Tests:** `tests/test_runtime_ui.py`, new UI adapter cases in
  `tests/test_pygame_renderer.py` and `tests/test_pygame_runtime.py`, plus the
  existing UI-model geometry/control/focus/pointer/nine-slice and legacy Pygame
  renderer/runtime suites. No reference implementation was copied; license
  status is therefore not applicable.
- **Evidence:** Commit `726d774` (with the narrow unsupported-blend fix in
  `2d2d9da`); runtime UI, renderer/runtime, pointer/focus/geometry, and
  nine-slice suites passed. Pure UI modules contain no Tk/Pygame imports.

### Task 5: Collider Authoring and Deterministic Physics Backend

- **Source symbols and destination:** Ursina `raycast.py` and hit-result test
  intent, plus Expra `HitResult2D` and `TriggerEvent` in `runtime/physics.py`,
  informed the boundary; Expra destinations are `ColliderComponent` and
  `PhysicsWorld2D.overlap`, `raycast`, and `step_triggers` in `runtime/`.
- **Behavior preserved:** Backend-neutral hit/trigger result shapes, inclusive
  contact, initial overlap, nearest ray hits, stable scene insertion ordering,
  layer/mask filtering, disabled/removed collider exclusion, and entered/
  stayed/exited lifecycle semantics.
- **Coupling removed:** Collider serialization contains only validated scalar,
  tuple, and bit-field data. Editor outline data is derived from the component
  and is not serialized; the world imports no renderer or editor backend.
- **Tests:** `tests/test_physics_world.py` covers validation, round-tripping,
  exact rectangle contact, filtering, deterministic raycast ties, disabled /
  removed colliders, and trigger lifecycle; `tests/test_runtime_physics.py`
  preserves the existing result-contract suite; component schema tests verify
  Task 1 metadata registration.
- **License/provenance:** Rewritten from scratch from Expra contracts and test
  intent; no reference implementation was copied, so license status is not
  applicable.
- **Evidence:** Commit `e6fb2f6`; collider validation, exact contact, filtering,
  deterministic ray ties, disabled/removed bodies, and enter/stay/exit tests
  passed. No solver or source-engine physics code was copied.

### Task 6: Shared Editor Viewport Preview

- **Source symbols and destination:** System Analyzer
  `tests/test_live_tk_resize.py` and Ursina `editor/level_editor.py` informed
  lifecycle/editor interaction intent; Expra destinations are
  `build_editor_render_target`, `ViewportPanel`, and camera interaction methods
  in `ui/viewport.py`, consuming existing renderer-neutral `RenderFrame`/
  `RenderItem` contracts and `extract_render_frame`; existing `Camera2D`
  projection owns editor pan, zoom, resize, and frame operations.
- **Behavior preserved:** Runtime visual colors, text payloads, phase/layer
  ordering, visibility/clipping, malformed-visual skipping, no-scene state,
  entity selection callbacks, and removed-selection safety. Grid, axes, entity
  labels, selection highlights, and collider outlines remain Tk-only overlays.
- **Coupling removed:** The preview does not duplicate scene extraction and
  does not make Tk Canvas the exported/runtime renderer; it consumes the same
  backend-neutral frame as runtime adapters. Collider outlines are derived
  editor data and never serialized as preview state.
- **Tests:** `tests/test_editor_render_targets.py` covers primitive/sprite/text
  extraction, colors, stable layer order, off-screen clipping, malformed
  visuals, removed selection, collider outlines, and bounded pan/zoom/frame/
  resize camera behavior. Existing `tests/test_editor_ui.py` covers real Tk
  no-scene, selection, resize, and marker callback regressions.
- **License/provenance:** Rewritten from Expra contracts and existing camera
  behavior; no reference implementation was copied, so license status is not
  applicable.
- **Evidence:** Commit `44b0fa7`; editor render-target tests and real-Tk xvfb
  tests passed for extraction, colors, ordering, clipping, malformed visuals,
  selection, collider outlines, pan/zoom/frame, and resize.

### Task 7: Space Pong Through the Real Workflow

- **Source symbols and destination:** Existing Expra `Project`,
  `ProjectWorkflow`, `Engine`, `ScriptRegistry`, `BehaviourSystem`,
  `GameCanvas`, `PygameRuntime`, generic visual/collider components, and
  `GameExporter`; destination is `SpacePongBehaviour` methods `on_start`,
  `on_fixed_update`, `score_point`, `toggle_pause`, `restart`, `resize`, and
  `examples/space_pong/` project data and entry point.
- **Behavior preserved:** Project-relative scene/script loading, edit/runtime
  scene isolation, play/pause/stop lifecycle, deterministic wall bounce and
  scoring, win state, restart, HUD layout under resize, hit feedback, generic
  render extraction, and standard standalone runtime assembly.
- **Coupling removed:** No engine module branches on Space Pong, project, or
  entity names. Game rules, tunables, tags, colors, UI labels, and scene content
  live under `examples/space_pong/`; runtime code consumes generic Expra APIs.
- **Tests:** `tests/test_space_pong.py` covers generic component inventory,
  script resolution, play/stop isolation, score/win/pause/restart/feedback,
  deterministic bounce, resize-stable HUD, render extraction, save/reopen,
  export packaging, and the standalone `PygameRuntime` path with an injected
  backend.
- **Editor evidence:** `xvfb-run` opened the project, selected the controller,
  edited an exposed script value and collider field, verified undo, played,
  paused, resumed, stopped, saved, and reopened the project. The command and
  JSON output are recorded in `docs/SPACE_PONG_FINAL_REPORT.md`.
- **Export evidence:** The real `expra_engine.export.cli` Linux export completed
  to `/tmp/opencode/space-pong-export/space_pong_linux`; the fake-packager test
  verifies project source, scripts, scenes, and launcher staging without network.
- **License/provenance:** Rewritten project content using Expra contracts; no
  reference repository or bundled asset was copied. License status is not
  applicable to the new project-owned code.
- **Evidence:** Commit `ed0fc68`; `tests/test_space_pong.py` passed 7 tests,
  including generic inventory, lifecycle, deterministic bounce, HUD resize,
  save/reopen, export, and standard runtime assembly. The xvfb editor command
  reported open/edit/undo/play/pause/resume/stop/save/reopen; export completed
  to `/tmp/opencode/space-pong-export/space_pong_linux`. Runtime execution used
  an injected backend, not a real display.

## Final Acceptance Record

Space-Pong-specific engine hacks: **MUST REMAIN NONE**.

The final report must provide concrete evidence for editor construction,
Inspector visual/collider/script editing, preview parity, runtime HUD/pause/win,
resize behavior, save/reopen, export, and standalone execution.
