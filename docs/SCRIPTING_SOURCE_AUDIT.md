# Expra Scripting Source Audit

This matrix records the current Expra baseline and the read-only extraction
from Ursina, PursuedPyBear (PPB), and MiniPyEngine. Reference repositories were
not modified.

## Sources reviewed

| Source | Evidence |
|---|---|
| Ursina | `ursina/entity.py`, `ursina/main.py`, `ursina/application.py`, `ursina/destroy.py`, `ursina/sequence.py`, `ursina/prefabs/hot_reloader.py`, `ursina/scripts/`, samples and tests |
| PPB | `src/ppb/engine.py`, `events.py`, `systemslib.py`, `scenes.py`, `gomlib.py`, input systems, and engine/event tests |
| MiniPyEngine | `Engine/StartGame.py`, `Engine/objects/GameObjectBase.py`, `GameObjects.py`, `Player.py`, `Level1.py`, `GMMKR.py`, `README.md` |
| Expra | Core/runtime/editor/filesystem/export modules and all related tests at base commit `783f051` |

## Matrix

| Source behavior / invariant | Expra equivalent | Status | Action |
|---|---|---:|---|
| Ursina owner-bound update/input scripts | `Entity` + `BehaviourSystem` | C | strengthen implementation |
| Ursina enabled filtering and input consumption | Entity/Behaviour enabled flags + `EventQueue` | B | add regression tests |
| Ursina simple `dt` gameplay hook | `Update.time_delta` | C | expose `on_update(dt)` |
| Ursina entity component convenience | `Entity.get_component` | B | add Behaviour helpers and required errors |
| Ursina lifecycle hooks | Engine play/stop and scene events | C | canonical Behaviour lifecycle |
| Ursina sequence/invoke ergonomics | `Timeline`, `Tween`, `Sequence`, `Repeater` | A/E | preserve existing ownership, add Behaviour context |
| Ursina hot reload lesson | no existing loader | C | staged import/reload with rollback |
| Ursina global scene/input/Panda coupling | explicit Expra owners | E | reject coupling |
| PPB single FIFO event queue | `EventQueue` | A | retain |
| PPB handler validation and error distinction | `BadEventHandlerException` | A | reuse |
| PPB scene transition flush | `Engine.push/pop/replace_scene` | A | add Behaviour transition tests |
| PPB explicit system lifecycle | `RuntimeSystem.start/stop` | A | Behaviour is not a system |
| PPB deferred nested signalling | `EventQueue.drain` | A | route Behaviour events here |
| PPB weak targeted delivery | Expra targeted list | E | retain explicit ownership; avoid hidden weak semantics |
| PPB startup rollback | Engine runtime startup | B | make Behaviour start atomic |
| MiniPyEngine `update(delta_time)` simplicity | Behaviour `on_update(dt)` | C | public ergonomic adapter |
| MiniPyEngine deferred destruction | scene/runtime mutation policy | C | stable snapshots and destroy-once tests |
| MiniPyEngine malformed map handling | resource/script validation | B | structured errors |
| ScriptComponent serialized identity | no existing implementation | C | add ResourceId-backed component |
| Exposed inspector metadata | existing Inspector/CommandStack seams | C | generic property editor integration |
| Resource-backed script registry | filesystem ResourceId/manifest | C | explicit registry and loader |
| Source/bytecode export | existing exporter | C | include registered script resources |
| Safe project script trust boundary | no script loader | C | forbid arbitrary serialized imports/paths |
| Runtime/editor Tk separation | export excludes editor/UI | A/E | verify with export tests |
| Separate script loop/queue | canonical Engine/EventQueue | E | never add one |

## Rejected patterns

- Ursina's singleton globals, Panda `NodePath` inheritance, arbitrary entity
  attributes, direct method replacement, and `exec`-based hot reload.
- PPB's inheritance-based `Children` model, SDL-specific input, and system
  set ordering where Expra needs deterministic order.
- MiniPyEngine's live-list removal while iterating and hard-coded map type
  dispatch.

## Evidence gaps closed by this pass

The implementation and tests must cover lifecycle ordering, start failure
atomicity, reentrancy, enabled state transitions, fixed timing, exposed field
validation/inheritance, serialization evolution, safe module resolution,
inspector undo/redo, export inclusion, and transactional reload failure.
