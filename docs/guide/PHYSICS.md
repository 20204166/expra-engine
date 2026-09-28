# Physics

Expra physics is a **deterministic query layer** (`PhysicsWorld2D`), not a full
rigid-body engine. There is no velocity integration, constraint solving, or
collision response.

## Colliders

`ColliderComponent` (type `"collider"`):

| Field | Default | Notes |
|---|---|---|
| `shape` | `"rectangle"` | `rectangle` or `circle` |
| `width` / `height` | `1.0` | rectangle only |
| `radius` | `None` | circle only |
| `offset` | `(0,0)` | from entity origin |
| `solid` | `True` | included in overlap queries |
| `trigger` | `False` | trigger detection only |
| `layer` | `1` | bitfield |
| `mask` | `0xFFFFFFFF` | bitfield |

## Layers and masks

Two colliders interact when **both** masks intersect the other's layer:

```python
first.mask & second.layer and second.mask & first.layer
```

## Queries

`PhysicsWorld2D` (`runtime/physics_world.py`):

- `overlap(body_id, *, include_triggers=True)` → overlapping entity ids.
- `raycast(origin, direction, distance, *, mask=…, include_triggers=True)` →
  nearest `HitResult2D`.
- `resolve_area_effect(body_id, …)` → `AreaEffect2D` (gravity/damping).
- `step_triggers()` → enter/stay/exit `TriggerEvent`s.

Positions are world-space, resolved through `scene.world_transform(entity_id)`
(parent-composed). Collider centers account for rotation and scale.

## Areas

`AreaComponent` (type `"area"`) requires a `ColliderComponent`. It overrides
gravity and linear/angular damping for overlapping bodies, with `SpaceOverride`
modes (`disabled|combine|combine_replace|replace|replace_combine`) and priority
ordering.

## Fixed update

`PhysicsWorld2D` has no internal fixed step — callers drive queries and
`step_triggers()` from the fixed-step clock (or wherever they choose). Engine
`Update` events drive `Behaviour.on_fixed_update`.

## What physics is not

- No rigid-body dynamics (no velocity/acceleration integration).
- No collision response (no penetration resolution or impulse application).
- No broadphase (deliberately broadphase-free).
- Not a 3D physics engine.

Layer combat hitboxes (melee arcs, projectiles) as colliders and query with
`overlap`/`raycast`, rather than expecting the physics layer to move bodies.
