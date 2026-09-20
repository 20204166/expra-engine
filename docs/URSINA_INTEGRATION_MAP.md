# Ursina to Expra Integration Map

## Audit Scope

This is a source audit of the supplied, unmodified Ursina tree at
`/home/btn17/Downloads/ursina-master`. The package declares version **Ursina
8.2.0** and **MIT** licensing in `pyproject.toml`; the full MIT notice is in
`LICENSE`. No Ursina source was edited and no Ursina implementation is copied
into Expra by this task.

Audit anchors: `Ursina 8.2.0`; `MIT`; no replaced Expra systems; no Panda dependency; no Tk game-runtime dependency.

Classifications are architectural decisions:

The audit uses **Classification A**, **Classification B**, **Classification C**,
**Classification D**, and **Classification E** exactly as defined below.

| Classification | Decision |
|---|---|
| A | Pure, useful semantics approved for a small Expra contract now |
| B | Useful behavior approved only after removing renderer/platform/global coupling |
| C | Platform or renderer seam; document and defer implementation |
| D | Editor-specific behavior; retain Expra editor ownership |
| E | Rejected for direct extraction; unsafe, redundant, or out of scope |

## Non-Negotiable Answers

- **No replaced Expra systems:** Expra `Entity`/`Component`, `Engine`,
  `EventQueue`, `RuntimeClock`, `RuntimeSystem`, coordinators, Tk editor, and
  wheel/release tooling remain the owners of their existing responsibilities.
- **No Panda dependency:** no Expra module or game export imports Panda3D,
  Ursina, `panda3d.core`, or renderer-specific vector/mesh/texture types.
- **No Tk game-runtime dependency:** Tk remains an editor adapter only; game
  runtime modules and exported games do not import `tkinter`, `ttk`, or the Tk
  delivery path.
- **No Tk game runtime:** a renderer-neutral runtime may not call the editor or
  use Tk widgets as its scene, input, timing, or drawing implementation.
- **No executable content from data:** dialogue and hot reload do not execute
  serialized or watched source text.

The final safety answers are: **no replaced Expra systems**, **no Panda
dependency**, and **no Tk game-runtime dependency**.

## Expra Ownership Rules

| Responsibility | Expra owner | Decision |
|---|---|---|
| Entity hierarchy and component data | `Engine`, `Scene`, `Entity`, `Component` | Do not import or wrap Ursina `Entity` |
| Update and timing | `RuntimeClock`, `RuntimeSystem`, existing update events | Do not create a second global clock or loop |
| Event delivery and UI commits | `EventQueue`, `AppCoordinator`, `UICoordinator`, `TkDeliveryQueue` | Do not call widgets from workers or use Ursina callbacks |
| Editor widgets and persistence | existing `src/expra_engine/ui` and editor coordinators | Preserve Tk editor ownership |
| Release and wheel generation | `scripts/build-wheel.sh`, release tests, package metadata | Ursina `build.py` is not an Expra release owner |
| Renderer and operating system | future explicit renderer/platform adapters | Keep Panda/window/collision details outside contracts |

## Implemented Expra Contracts

The implemented extraction destinations are small, renderer-neutral contracts,
not copied Ursina subsystems:

| Destination | Contract recorded by the implementation |
|---|---|
| `core/safe_expression.py` | Canonical shared owner for bounded numeric arithmetic; no names, calls, attributes, indexing, `eval`, or `exec` |
| `editor/safe_expression.py` | editor safe_expression re-export boundary; the editor does not own a second parser |
| `runtime/input.py` | physical-input to semantic-action contract with instance-scoped bindings and held state |
| `runtime/timeline.py` | Update-driven scaled/unscaled timeline contract using `RuntimeSystem` and existing update events |
| `runtime/animation.py` | immutable sprite animation contract for metadata, sheet regions, clips, and named state control |
| `runtime/follow.py` | exponential 2D follow contract over plain values, including validated speed and offset |
| `runtime/tilemap.py` | renderer-neutral tilemap contract for bounded layers, neighbor masks, and local deterministic variation |
| `runtime/dialogue.py` | typed dialogue graph contract with explicit conditions/actions and bounded transitions |
| `editor/assets.py` | async asset scan contract; scheduling remains with `AppCoordinator` and delivery remains with `TkDeliveryQueue` |

These contracts have no Panda/Ursina/Tk game runtime. The existing
coordinator owners remain the owners, and existing release tooling remains the
owner of wheel/build/release behavior. Hot reload is limited to controlled
asset invalidation rather than `exec`; window/display settings belong behind a
platform backend.

Task 12 boundary statements: `core.safe_expression` is canonical and
`editor.safe_expression` is the editor safe_expression re-export boundary;
existing release tooling remains the owner and existing coordinator owners remain the owners. This records controlled asset invalidation rather than exec,
window/display settings belong behind a platform backend, renderer implementation remains deferred, color/gradient editing remains deferred, and grid editor remains deferred.

## Core Runtime And Platform Sources

| Ursina source | Class | Useful semantics | Coupling removed or rejected | Expra destination, tests and edge cases |
|---|---|---|---|---|
| `ursina/entity.py` | E | Parent/child objects, enabled state, lifecycle hooks, input/update names | Duplicates Expra entity/component ownership and relies on scene globals/render nodes | None. Existing engine/entity tests remain authoritative |
| `ursina/input_handler.py` | B | Named physical events, press/release/hold, modifier composition, rebinding | Remove module globals `held_keys`/`rebinds`; use instance-scoped identifiers/actions | `runtime/input.py`; test independent instances, absent unbind, modifiers, focus loss |
| `ursina/mouse.py` | B/C | Position, delta, drag delta, hover, click/double-click, capture-like pressed state | Remove Panda collision traverser, `base`, scene/camera globals and implicit callbacks | `runtime/pointer.py` plus future platform adapter; test enter/leave, outside release, capture, drag, double-click, focus loss |
| `ursina/window.py` | C | Size/aspect/fullscreen/borderless/title/vsync concepts and screen corners | Remove `WindowProperties`, Panda PRC, monitor/X11 calls, render-mode mutation and editor UI | Future platform backend; geometry consumes logical size/safe area; test invalid sizes and aspect changes |
| `ursina/application.py` | C/E | Application lifecycle, pause/development mode, asset roots, quit | Global Panda application and editor/debug singleton are not Expra runtime contracts | Existing `Engine`/runtime lifecycle; test start/stop/pause via existing events |
| `ursina/sequence.py` | B | Ordered delay/tween/callback composition and cancellation intent | Remove global invoke state, renderer callbacks and unbounded zero-duration behavior | `runtime/timeline.py` on `RuntimeClock`; test delay, order, cancellation, pause, large delta, scaled/unscaled time |
| `ursina/scripts/grid_layout.py` | B | Chunk a list into rows and place items by bounds, origin, spacing and offset; absolute spacing is also supported | Remove Ursina `Vec2`, `chunk_list`, mutable entity bounds/position and scene objects | `ui_model/geometry.py`; test empty/invalid input, `max_x`, origins, spacing, offsets, varying item sizes and absolute-spacing behavior |
| `ursina/scripts/scrollable.py` | B | Track a scroll target, respond to wheel direction over an entity or descendant, clamp to min/max and smooth toward the target | Remove global `mouse`/`time`, entity ancestry/hover state and direct axis mutation; define zero targets and input ownership explicitly | `ui_model/controls.py`; test hover ancestry, ignored input, up/down direction, clamp, smoothing, focus loss and zero-valued targets |
| `ursina/scripts/smooth_follow.py` | B | Follow a target with exponential position convergence, offset and optional rotation convergence | Remove Ursina world transforms and global `time`; reject or define invalid speeds and make target/lifecycle ownership explicit | `runtime/follow.py`; test no target, offset, position convergence, optional rotation, zero/negative speed and large delta |
| `ursina/vec2.py`, `vec3.py` | A | Small 2D/3D arithmetic vocabulary | Do not depend on Ursina vector classes or mutable renderer values | Existing Expra 2D values and pure dataclasses; test arithmetic and no Ursina imports |
| `ursina/color.py` | A/B | RGBA/HSV conversion and interpolation | Remove global color namespace and renderer color objects | `expra_engine.design` and future pure color contracts; test alpha, clamping, HSV round trips |
| `ursina/text.py` | C/E | Text content, wrapping, alignment and measured-size concepts | Font rasterization, shader tags, scene entities and measurement are backend work | Future renderer text protocol; no direct extraction |
| `ursina/trigger.py` | E | Trigger callback concept | Collider and global scene ownership duplicate future runtime interaction work | Defer until a collision contract exists |
| `ursina/duplicate.py` | E | Entity duplication convenience | Copies renderer/entity graphs and bypasses Expra component lifecycle | No destination; use explicit Expra scene/component cloning if required |
| `ursina/gamepad.py` | C | Device axes/buttons and dead-zone intent | OS/device polling and Panda event source are platform concerns | Future adapter feeds `runtime/input.py`; test normalized axes/disconnects later |
| `ursina/music_system.py` | C/E | Track/loop/fade concepts | Audio backend, global application state and asset loading are out of scope | Defer to an audio service contract |
| `ursina/mesh.py`, mesh import/export modules | E | Mesh vertex/index/UV data concepts | Panda mesh objects, conversion and renderer upload are not neutral UI data | No direct destination; exporter remains future work |

## UI Prefabs And Controls

| Ursina source | Class | Useful semantics | Coupling removed or rejected | Expra destination, tests and edge cases |
|---|---|---|---|---|
| `prefabs/button.py` | B | Normal/hover/pressed/disabled states, text/icon and click semantics | Remove Entity, collider, mouse singleton, Audio, shader/model mutation and callback side effects | `ui_model/controls.py`; test disabled input, enter/leave, press/release, text type, selected state |
| `models/procedural/nine_slice.py` | B | Nine-patch corners/borders/center, aspect behavior, outset | Replace Panda `Mesh`, mutable vertices and implicit radius math with validated logical rectangles | `ui_model/nine_slice.py`; test tiny/wide/tall/square, oversized borders, outset, nonnegative patches |
| `prefabs/slider.py` | B | Min/max/default/step, drag, dynamic versus commit notifications, vertical orientation | Remove Draggable/collider/global mouse, delayed invoke and direct setattr | `ui_model/controls.py`; test inverted range, clamp, step, live/commit, click/release |
| `prefabs/checkbox.py` | B | Boolean toggle and visual state | Remove Entity/Button/callback rendering | `ui_model/controls.py`; test repeated toggles, disabled state and initial value |
| `prefabs/button_group.py` | B | Selection grouping and constrained choices | Remove child Entity scan and implicit click dispatch | `ui_model/controls.py`; test minimum/maximum selection and disabled members |
| `prefabs/button_list.py` | B | Ordered choices, hover marker, selected item, click-outside clearing | Remove camera.ui, mouse point and scene child ownership | Selection/focus contracts; test empty list and out-of-bounds pointer |
| `prefabs/dropdown_menu.py` | B | Popup choice list, selection and close-on-selection/outside | Remove global UI hierarchy and collider hit testing | Future renderer control; test keyboard/focus, outside click and empty options |
| `prefabs/input_field.py` | B/D | Content filtering, character limit, active/submit, next field and masked display | Remove TextField rendering/clipboard/global held keys and delayed mouse movement | `editor/safe_expression.py` plus existing inspector/editor owner; test invalid input, submit, focus, masking |
| `prefabs/text_field.py` | B/D | Cursor/selection, multiline editing, undo/redo, scrolling, word movement, shortcuts | Remove Text/Entity rendering, Panda coordinates, pyperclip, wall clock and global held keys | Editor text behavior remains editor-owned; test a state model only if later required |
| `prefabs/vec_field.py` | D | Multi-component numeric editing, drag increments, int/float distinction | Reject `eval` at source line 51; remove nested renderer fields and mouse velocity | `editor/safe_expression.py` then inspector; test arithmetic allow-list, NaN/inf, malformed input, rounding, undo records |
| `prefabs/color_picker.py` | B/D | HSV/RGBA editing, alpha, preview and change notification | Remove Slider/Entity/texture gradients and renderer color types | Future pure color editor contract; test HSV boundaries, alpha and dynamic/commit notifications |
| `prefabs/gradient_editor.py` | B/D | Ordered color stops, preview, stop editing and hex serialization | Remove Mesh/Plane/pyperclip and mutable closure callbacks | Deferred editor gradient model; test duplicate/out-of-range stops, resolution and stable serialization |
| `prefabs/radial_menu.py` | B | Radial choice arrangement and selection | Remove camera transforms, colliders and global mouse angle calculation | Deferred renderer-neutral menu; test zero/one/many choices, angle wrap and keyboard fallback |
| `prefabs/panel.py`, `window_panel.py` | B | Panel hierarchy, title/content regions, close/drag intent | Remove model/texture/shader and scene ownership | Future renderer UI tree; test layout intent and close state |
| `prefabs/tooltip.py`, `cursor.py` | B/C | Hover delay, tooltip content, cursor visibility/style | Remove global hover and platform cursor mutation | Future pointer/renderer adapter; test delay, disabled target and pointer exit |
| `prefabs/health_bar.py` | B | Clamped progress and optional text | Keep generic value/max; reject health meaning in generic UI model | `ui_model/controls.py`; game component owns health; test zero/max and over/underflow |
| `prefabs/options_menu.py`, `main_menu.py`, `pause_menu.py` | B/D | Menu state, navigation and pause/resume intent | Remove application singleton, scene globals, renderer tree and direct pause mutation | Existing runtime/editor owners plus future UI model; test empty menu, focus and pause ownership |
| `prefabs/memory_counter.py`, `made_with_ursina.py`, `splash_screen.py` | E/C | Diagnostics, branding and timed splash | Not extraction contracts; renderer/app-shell policy | Defer to app shell/platform policy |

## 2D, Animation, And Editor Prefabs

| Ursina source | Class | Useful semantics | Coupling removed / Expra destination |
|---|---|---|---|
| `prefabs/tilemap.py` | B | Grid pixels, eight-neighbor masks, autotile UV choice, deterministic per-cell variation and save intent | Remove texture pixels, Mesh, colliders, global `random.seed`, printing and file writes. `runtime/tilemap.py`; test boundaries, local seed, layers and save boundary |
| `prefabs/grid_editor.py` | D | Grid cursor, palette, draw/erase/fill, selection, copy/paste, undo/redo | Keep editor ownership; remove camera.ui, collider meshes, global mouse and renderer previews. Test flood fill, selection and undo/redo |
| `prefabs/animation.py`, `sprite_sheet_animation.py`, `frame_animation_3d.py`, `animator.py` | B/C | Frame clips, FPS/durations, looping, named states, play/pause | Remove texture/model mutation, global update, renderer asset loading and 3D mesh assumptions. `runtime/animation.py`; test duration validation, loop, pause/resume and missing clips |
| `prefabs/sprite.py` | C | Texture identity, aspect and pixels-per-unit concepts | Texture upload/filtering and sprite object are future backend work | Renderer-facing metadata only in future animation contract |
| `prefabs/draggable.py` | B | Drag start/update/drop, axis locks and bounds | Remove collider and global mouse | `runtime/pointer.py`; test capture, bounds, outside drop and focus loss |
| `prefabs/platformer_controller_2d.py`, `first_person_controller.py`, `editor_camera.py` | C/E | Movement actions, camera follow/orientation intent | Physics, collision raycasts, camera and input globals are not current pure scope | Defer behind platform/physics contracts |
| `prefabs/particle_system.py`, `trail_renderer.py`, `video_recorder.py` | C/E | Emitter, trail and capture concepts | Renderer/GPU/video platform coupling | Deferred renderer services |
| `prefabs/sky.py`, `primitives.py`, `ascii_editor.py` | C/D/E | Background, primitive shape and grid/text editing concepts | Sky/primitives require renderer; ASCII editor is editor-specific | Defer or retain editor-only implementation |

## Data, Dialogue, Reloading, And Build Sources

| Ursina source | Class | Useful semantics | Coupling removed / destination and tests |
|---|---|---|---|
| `prefabs/conversation.py` | B/D | Indented dialogue graph, multi-page content, choices, conditions, explicit mutations and reveal timing | Reject string `if`/assignment execution, `getattr`, callback closures and renderer animation. `runtime/dialogue.py`; test malformed indentation, missing variables, typed conditions/actions, branch limits and terminal nodes |
| `prefabs/hot_reloader.py` | C/E | File change detection and controlled asset invalidation idea | Reject `exec(text)` at source lines 135-138, scene clearing, global pause/camera and direct shader/model mutation | Future controlled asset invalidation; test stale generations, invalid source reporting and no code execution |
| `build.py` | E | Build phases, asset copying, cache, platform names and overwrite confirmation | Not compatible with Expra wheel/release owner; downloads Windows Python, mutates folders and writes `.bat` | `scripts/build-wheel.sh`, release tests and metadata remain owners |
| `prefabs/file_browser.py`, `file_browser_save.py` | D | Folders-first sorting, filtering, selection limit, navigation, open/save and overwrite intent | Remove synchronous `Path.iterdir()` on the UI path, widget creation and direct callbacks | `editor/assets.py` through `AppCoordinator`/`TkDeliveryQueue`; test permission/missing folders, empty results, stale generation, cancellation, overwrite |
| `scripts/property_generator.py`, `string_utilities.py`, `ursinamath.py` | E/B | Property convenience, string replacement and interpolation/decay math | Do not import broad Ursina helpers; selectively re-express mathematical semantics in typed pure modules | Existing Expra utility ownership or focused runtime modules; test finite values, bounds and no global mutation |

## Complete Neighbor Inventory

The required neighboring families were checked, not treated as isolated
examples. UI prefabs are `button.py`, `button_group.py`, `button_list.py`,
`checkbox.py`, `dropdown_menu.py`, `slider.py`, `panel.py`, `window_panel.py`,
`tooltip.py`, `cursor.py`, `input_field.py`, `text_field.py`, `vec_field.py`,
`color_picker.py`, `gradient_editor.py`, `radial_menu.py`, `options_menu.py`,
`main_menu.py`, `pause_menu.py`, `conversation.py`, `file_browser.py`, and
`file_browser_save.py`. 2D/editor prefabs are `grid_editor.py`, `tilemap.py`,
`sprite.py`, `animation.py`, `sprite_sheet_animation.py`,
`frame_animation_3d.py`, `animator.py`, `draggable.py`,
`platformer_controller_2d.py`, `ascii_editor.py`, and `editor_camera.py`.
Presentation/service prefabs are `health_bar.py`, `memory_counter.py`,
`hot_reloader.py`, `particle_system.py`, `trail_renderer.py`,
`video_recorder.py`, `sky.py`, `primitives.py`, `splash_screen.py`, and
`made_with_ursina.py`. Core/platform/export areas are `entity.py`,
`input_handler.py`, `mouse.py`, `window.py`, `application.py`, `sequence.py`,
`gamepad.py`, `build.py`, `mesh.py`, `mesh_importer.py`, `mesh_exporter.py`,
`text.py`, `color.py`, `vec2.py`, `vec3.py`, `trigger.py`, `duplicate.py`, and
`music_system.py`. Procedural models checked are `nine_slice.py`, `quad.py`,
`plane.py`, `grid.py`, `circle.py`, `cube.py`, `cone.py`, `cylinder.py`,
`capsule.py`, `pipe.py`, and `terrain.py`; only `nine_slice.py` is a UI
geometry candidate. Samples demonstrate composition but are not copied.

## Approved Destinations And Test Matrix

| Destination | Required contract coverage |
|---|---|
| `ui_model/geometry.py` | Anchors, pivots, offsets, fixed/stretch sizes, DPI/reference scaling, aspect ratios, safe areas, negative sizes and inverted safe areas |
| `ui_model/nine_slice.py` | Immutable patches, tiny/wide/tall panels, clamped borders, outset/padding and no negative rectangles |
| `ui_model/controls.py` | Button/toggle/slider/selection/progress transitions, disabled input, ranges, clamp, step, live/commit |
| `ui_model/focus.py` | Deterministic next/previous traversal, skipped/disabled items and wrap policy |
| `runtime/input.py` | Physical/action mapping, held state, modifiers, collision policy, focus reset and independent instances |
| `runtime/pointer.py` | Hover, press/release, capture, drag/drop, double-click, outside release and focus loss |
| `runtime/timeline.py` | Delay, interpolation, callback order, cancellation, pause, loops, large deltas and scaled/unscaled time |
| `runtime/animation.py` | Immutable metadata, frame regions/durations, looping, pause/resume and named transitions |
| `runtime/follow.py` | Exponential convergence, zero speed, negative speed rejection and large delta |
| `runtime/tilemap.py` | Empty/one-cell maps, edge/corner masks, bounds, local variation, layers and no global RNG mutation |
| `runtime/dialogue.py` | Typed nodes, choices, safe conditions/actions, malformed indentation, missing variables and branch limits |
| `core/safe_expression.py` with `editor/safe_expression.py` re-export | Numeric constants/arithmetic only; reject names, calls, attributes, indexing, imports, `eval`, `exec`, NaN/inf and oversized expressions |
| `editor/assets.py` | Sorting/filtering/navigation, open/save, overwrite, cancellation, stale generations, missing/permission folders and empty results |

Existing Expra tests remain regression coverage for engine, runtime events,
clock, coordinators, editor UI, persistence and release behavior. The focused
audit contract is `tests/test_ursina_integration_map.py`.

## Deferred Features

Renderer implementation remains deferred, as do text shaping and platform
window/display settings;
Panda-like collision and physics; audio/music; shaders, meshes and video;
mobile touch remains deferred; radial menu remains deferred; grid editor
remains deferred; grid/tilemap editor rendering; color/gradient editing remains
deferred; dialogue presentation remains deferred; hot reload; standalone export;
and Ursina-style sample/game controllers are recorded as deferred. Each needs
an explicit Expra owner, backend seam, lifecycle policy and tests.

## Rejected Patterns

- Replacing Expra `Entity`, `Component`, `Engine`, event queue, clock,
  coordinators, editor or release scripts with Ursina equivalents.
- Importing Ursina or Panda3D into Expra runtime or UI model packages.
- Using global `mouse`, `held_keys`, `rebinds`, `camera.ui`, scene registry,
  RNG or clock as hidden state.
- Using `eval`/`exec` for `VecField`, dialogue actions or hot reload.
- Rendering a game UI with Tk widgets or running game runtime through the Tk
  editor delivery queue.
- Copying synchronous file enumeration into the Tk thread.
- Treating `build.py` as the Expra wheel/release implementation.
- Copying Panda meshes, colliders, shaders, textures or mutable renderer
  objects into pure data contracts.

## Provenance And License Decision

Version and license were verified directly in
`/home/btn17/Downloads/ursina-master/pyproject.toml` and
`/home/btn17/Downloads/ursina-master/LICENSE`. The source is MIT licensed. If
a future change adapts substantial Ursina implementation, Expra must retain
the Ursina copyright/license notice in `THIRD_PARTY_NOTICES.md` and identify
the adapted files. This task adapts no substantial implementation, so that
notice file is intentionally unchanged.

## Validation Evidence

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`: **477 passed**.
- `.venv/bin/ruff check src tests`: **passed**.
- `.venv/bin/pyright`: **0 errors, 0 warnings**.
- `.venv/bin/mypy src tests`: **no issues found in 103 source files**.
- `git diff --check`: **passed**.
- `xvfb-run -a .venv/bin/python` editor lifecycle smoke: **passed**.
- `./scripts/build-wheel.sh && ./scripts/verify-wheel.sh`: wheel `0.1.7.1`,
  66 members, no forbidden paths, checksum verified.
- Searches for Ursina/Panda imports, `camera.ui`, `eval`/`exec`, and Tk imports
  under `runtime/`: **no matches**.

## Final Audit Report

- **Areas audited:** requested Ursina UI prefabs, layout/scroll scripts,
  text/input/mouse/window sources, nine-slice, animation/timing, sprites,
  smooth follow, tilemap/grid editor, dialogue, hot reload, file browser,
  color/gradient tools, build/export, and platform/window boundaries.
- **HIGH VALUE / LOW RISK applied:** logical UI geometry, safe areas,
  reference resolution, nine-slice patches, pure controls, focus/pointer
  contracts, action maps, deterministic timelines, sprite animation metadata,
  smooth follow, tilemap data, typed dialogue, safe arithmetic, and asset scan
  contracts.
- **MEDIUM VALUE / MODERATE RISK retained as seams:** renderer-backed widgets,
  platform display/input adapters, dialogue presentation, grid editor rendering,
  mobile touch, and game export.
- **LOW VALUE / HIGH RISK rejected:** Panda entity/window/mesh/collider ports,
  global Ursina state, direct hot reload, arbitrary code execution, and direct
  Ursina build integration.
- **Canonical owners reused:** Expra Entity/Component/Scene/Engine,
  RuntimeClock/EventQueue/RuntimeSystem, AppCoordinator, TkDeliveryQueue,
  UICoordinator, design tokens, persistence, and release tooling.
- **Specialized callers retained:** editor ButtonCoordinator and Tk UI remain
  editor-only; runtime input/timeline/UI models remain renderer-neutral; asset
  scanning remains coordinator-owned; health remains a caller meaning layered
  over generic progress.
- **Redundant implementations removed:** none; this pass added independent
  Expra contracts and copied no substantial Ursina implementation.
- **Runtime work reduced:** no global scheduler, per-frame mouse polling,
  process-global RNG mutation, UI-thread enumeration, or second clock was
  introduced.
- **Security/platform/lifecycle:** safe arithmetic is AST-bounded; dialogue
  data cannot execute code; runtime imports no editor/Tk module; Panda/Ursina
  are absent; pause/unscaled timing is explicit and injected because existing
  paused Engine ticks emit no updates.
- **Remaining opportunities:** renderer implementation, text shaping and
  input adapters, UI screen stack, scroll/grid layout adapters, audio/physics,
  color/gradient editor models, controlled hot reload, and standalone export.

## Final Decision

URSINA EXTRACTION MAP COMPLETE — EXPRA-ADAPTED FOUNDATION READY
