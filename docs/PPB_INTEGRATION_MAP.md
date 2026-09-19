# PPB Integration Map

How PursuedPyBear (Artistic License 2.0) informed expra-engine maturation.

## Classification Key

| Code | Meaning |
|---|---|
| A | Expra already has a mature equivalent — PPB not used |
| B | Expra has a partial version — improved using PPB semantics |
| C | New capability integrated from PPB |
| D | Future reference — concept noted, not yet integrated |
| E | Excluded — PPB/SDL-specific or otherwise not relevant |

---

## PPB Capability Classification

| PPB Capability | PPB Source | Classification | Expra Decision |
|---|---|---|---|
| `camel_to_snake`, `get_time` | `utils.py` | **C** | Integrated → `core/utils.py` |
| `BadEventHandlerException` | `errors.py` | **C** | Integrated → `core/errors.py` |
| `BadChildException`, `NotMyChildError` | `errors.py` | **C** | Integrated → `core/errors.py` |
| Runtime event queue (signal/publish/FIFO/handler names) | `engine.py` (GameEngine) | **C** | Integrated → `runtime/event_queue.py` |
| Event dataclasses (Update/Idle/Quit/SceneStarted/…) | `events.py` | **C** | Integrated → `runtime/events.py` (PPB fields removed) |
| Fixed-timestep clock (Updater) | `systems/clocks.py` | **C** | Integrated → `runtime/clock.py` |
| `loop_once()` / external-loop embedding | `engine.py` | **C** | Integrated → `Engine.tick()` + `Engine.loop_once()` |
| Runtime scene stack (push/pop/replace) | `engine.py` | **C** | Integrated → `Engine.push_scene/pop_scene/replace_scene` |
| Scene lifecycle events (SceneStarted/Stopped/Paused/Continued) | `engine.py` | **C** | Integrated → `runtime/events.py` + Engine dispatches them |
| RuntimeSystem lifecycle | `systemslib.py` | **C** | Integrated → `runtime/system.py` |
| Entity tags (tag-based query) | `gomlib.py` (Children tags) | **C** | Integrated → `Entity.add_tag/remove_tag/has_tag/tags` |
| Scene queries (by tag / component) | `gomlib.py` (Children.get) | **C** | Integrated → `Scene.get_entities(tag=, component=)` |
| Hierarchy traversal (`walk()`) | `gomlib.py` | **C** | Integrated → `Scene.walk_hierarchy()` (BFS, DFS) |
| Camera coordinate math (world↔screen) | `camera.py` | **C** | Integrated → `core/camera.py` (Camera2D, no SDL) |
| Camera visibility (`point_is_visible`) | `camera.py` | **C** | Integrated → `Camera2D.point_is_visible()` |
| Camera width/height/aspect ratio | `camera.py` | **C** | Integrated → `Camera2D.width/height` coupled setters |
| `Engine.update()` (legacy timing shim) | Expra origin | **A** | Preserved unchanged |
| Edit/play/pause/stop state machine | Expra origin | **A** | Preserved unchanged |
| JSON round-trip scene isolation | Expra origin | **A** | Preserved unchanged |
| AppCoordinator / UICoordinator / etc. | Expra origin | **A** | Not touched — different domain |
| TkDeliveryQueue | Expra origin | **A** | Not touched |
| Flag singleton metaclass | `flags.py` | **A** | Python Enum covers this adequately |
| `GameObject` / `Children` container | `gomlib.py` | **A/B** | Entity+Scene model already covers this; hierarchy/tags added to existing types |
| PPB `Scene` (background color, camera_class) | `scenes.py` | **A** | Expra Scene is cleaner for an editor; not replaced |
| Two-phase Update/Commit | `features/twophase.py` | **D** | Good pattern; document as future RuntimeSystem |
| Frame-by-frame animation | `features/animation.py` | **D** | Future: AnimationComponent when asset system exists |
| Loading scene / progress | `features/loadingscene.py` | **D** | Expra AppCoordinator already handles background progress |
| Asset system (AbstractAsset, background load) | `assetlib.py` | **D** | Future phase; Expra needs an asset-neutral contract first |
| VFS / package resource resolution | `vfs.py` | **D** | Future: project-relative resource resolution |
| Input events (KeyPressed/MouseMotion/etc.) | `events.py`, `systems/inputs.py` | **D** | Future: abstract contract + Tk/SDL adapters |
| Renderer abstraction + layers | `systems/renderer.py` | **D** | Future: Tk viewport is placeholder; needs backend contract |
| SDL EventPoller | `systems/inputs.py` | **E** | SDL-specific; excluded from core |
| SDL Renderer | `systems/renderer.py` | **E** | SDL-specific; excluded |
| SoundController + PyAudio | `systems/sound.py` | **E** | SDL/audio-backend-specific; excluded |
| `ppb_vector.Vector` | external dep | **E** | Replaced by plain float tuples in Camera2D |
| PPB `Sprite` inheritance model | `sprites.py` | **E** | Expra uses composition (Entity+Component) not inheritance |
| `changelib.py` (deprecated wrappers) | `changelib.py` | **E** | Depends on `deprecated` package; not needed in new codebase |

---

## Integrated Capabilities (detailed)

### 1. Core Utilities (`core/utils.py`)
- **PPB source:** `src/ppb/utils.py`
- **Existing Expra code extended:** None (new file)
- **Behavior preserved:** `camel_to_snake` regex, `get_time` as perf_counter
- **Behavior omitted:** `LoggingMixin` (frame-hack), module-file index
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 2. Error Types (`core/errors.py`)
- **PPB source:** `src/ppb/errors.py`
- **Existing Expra code extended:** None (new file)
- **Behavior preserved:** Helpful diagnostic message format in `BadEventHandlerException`
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 3. Runtime Event Queue (`runtime/event_queue.py`)
- **PPB source:** `src/ppb/engine.py` (GameEngine signal/publish pattern)
- **Existing Expra code extended:** None (new file); Engine calls `tick()` which drives it
- **Behavior preserved:** FIFO ordering, handler names via camel_to_snake, targeted delivery, deferred signal (events signalled inside handlers enqueue, not immediate), flush-before-scene-transition, `BadEventHandlerException` on bad signature
- **Behavior omitted:** WeakSet targets (plain list instead), event_extensions (hydration callbacks)
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 4. Runtime Events (`runtime/events.py`)
- **PPB source:** `src/ppb/events.py`
- **Existing Expra code extended:** None (new file)
- **Behavior preserved:** Event names (Update, Idle, Quit, SceneStarted, SceneStopped, ScenePaused, SceneContinued, StartScene, StopScene, ReplaceScene), dataclass structure
- **Behavior omitted:** All PPB-specific fields (scene, Vector position, MouseButton, KeyCode)
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 5. Runtime Clock (`runtime/clock.py`)
- **PPB source:** `src/ppb/systems/clocks.py` (Updater)
- **Existing Expra code extended:** None (new file)
- **Behavior preserved:** Fixed-timestep accumulator logic; carry-forward fraction; spiral-of-death prevention; multiple Updates per Idle when wall clock outpaces step
- **Behavior omitted:** System base class; `__enter__/__exit__`
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 6. Engine tick/loop_once + Scene Stack (`core/engine.py`)
- **PPB source:** `src/ppb/engine.py` (GameEngine.loop_once, EngineChildren scene stack)
- **Existing Expra code extended:** Engine — additive only; `update()` preserved unchanged
- **Behavior preserved:** `loop_once()` external-loop semantics; scene stack push/pop/replace; flush-before-transition; SceneStopped/SceneStarted/ScenePaused/SceneContinued dispatch; auto-Quit on empty stack
- **Behavior omitted:** EngineChildren Children-based management (Expra uses list); WeakSet event targets
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 7. Entity Tags + Scene Queries
- **PPB source:** `src/ppb/gomlib.py` (Children.add tags, Children.get)
- **Existing Expra code extended:** `Entity` (additive: `_tags`, `add_tag/remove_tag/has_tag/tags`); `Scene` (additive: `get_entities_by_tag/by_component/get_entities`)
- **Serialization impact:** `Entity.to_dict()` now includes `"tags": [...]`; `from_dict()` loads it; legacy dicts without `tags` key load cleanly
- **Behavior preserved:** Kind+tag intersection semantics (PPB `get(kind=X, tag=Y)`); `TypeError` when no filter passed
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 8. Entity Hierarchy + Walk
- **PPB source:** `src/ppb/gomlib.py` (walk function, Children tree traversal)
- **Existing Expra code extended:** `Scene` (additive: `children_of`, `roots`, `set_entity_parent`, `walk_hierarchy`)
- **Behavior preserved:** BFS walk order (parent before children); cycle detection; self-parent guard
- **Behavior omitted:** Recursive Children container (Expra uses flat list + parent_id index)
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

### 9. Camera2D (`core/camera.py`)
- **PPB source:** `src/ppb/camera.py`
- **Existing Expra code extended:** None (new file)
- **Behavior preserved:** pixel_ratio calculation; width/height aspect-ratio coupling; translate_to_screen/translate_to_game inverse pair; point_is_visible inclusive boundary; edge properties (left/right/top/bottom/corners); TypeError on invalid point
- **Behavior omitted:** ppb_vector.Vector dependency (plain tuples); Renderer reference; RectangleShapeMixin; sprite_in_view (sprite-model-specific)
- **License/provenance:** Adapted; see THIRD_PARTY_NOTICES.md

---

## Excluded PPB Features (with reasons)

| Feature | Reason |
|---|---|
| `sprites.py` (Sprite, RotatableMixin, RectangleShapeMixin) | SDL/ppb_vector dependent; Expra uses Entity+Component composition |
| `systems/renderer.py` | SDL-specific; Expra has a Tk placeholder; real renderer is a future decision |
| `systems/inputs.py` | SDL event types; abstract input contract is a future phase |
| `systems/sound.py` / `systems/text.py` | SDL/audio-backend specific |
| `systems/sdl_utils.py` | SDL utilities; not portable |
| `changelib.py` | Depends on `deprecated` pip package; not needed in a new codebase |
| `buttons.py`, `keycodes.py` | SDL SDL event enums; future input abstraction will be backend-neutral |
| `camera.py:sprite_in_view` | Requires rectangular sprite API not in Expra yet |
| `assetlib.py` (background loader) | Complex SDL-coupled; future design must be backend-neutral |
| `vfs.py` | Future: project-relative resource resolution needed first |
| `features/animation.py` | Requires asset system first |
| `features/twophase.py` | Future RuntimeSystem candidate; no concrete use-case yet |
| `features/loadingscene.py` | Expra AppCoordinator handles progress; no competing implementation wanted |
| PPB `Engine.event_extensions` | Not needed yet; can add later if required |
| PPB `GameEngine` as a whole | Expra Engine owns state differently; took only the mechanisms, not the class |

---

## Architectural Collisions

**None identified.** All integrated capabilities were additive:
- Existing Engine public API unchanged (`play/pause/stop/update/set_scene/set_project`)
- Existing Entity/Scene public API unchanged (tags/hierarchy added, nothing removed)
- Existing serialization format backward-compatible (`tags` key optional on load)
- Editor infrastructure (AppCoordinator, UICoordinator, etc.) not touched
