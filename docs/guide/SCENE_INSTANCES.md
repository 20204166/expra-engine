# Scene Instances

A **Scene Instance** places a reusable Scene into another Scene (or Level) as a
single entity, then materializes a deep copy of the source Scene's hierarchy as
children.

## The component

`SceneInstanceComponent` (type `"scene_instance"`):

| Field | Type | Default | Meaning |
|---|---|---|---|
| `source_path` | `str` | `""` | project-relative source Scene path (required) |
| `overrides` | `dict[str, dict]` | `{}` | per-entity-name override of `ScriptComponent.exposed_values` |
| `enabled` | `bool` | `True` | |

```python
entity.add_component(SceneInstanceComponent("scenes/hud.scene.pb"))
```

## How it works

1. An instance is an ordinary `Entity` carrying a `SceneInstanceComponent`. Its
   own `TransformComponent` is the root transform override.
2. On load (and re-resolve), `resolve_scene_instances` deep-copies the source
   Scene's hierarchy as child entities under the instance root.
3. Materialized children are tracked but **never serialized** — they are
   regenerated on every load. (`Scene.to_dict(include_instance_content=False)`.)

## Source identity vs instance identity

- **Instancing** keeps source identity: materialized children re-resolve from
  source on each load.
- **Duplicating** (`Scene.clone_entity`) makes an independent copy with no
  source link.

## Nesting and cycles

- Nesting is supported: a source Scene may itself contain instances.
- Cycles are detected and raise `SceneInstanceCycleError`.
- **Levels are rejected** as instance sources (`SceneInstanceSourceError`).

## Overrides (Phase 1 — limited)

Overrides map a materialized entity **name** → `{exposed_value_key: value}`,
applied after materialization. Current limitations:

- only the **first** entity matching a name is targeted;
- entities without a `ScriptComponent` are skipped;
- no deeper override inheritance.

## Errors

- `SceneInstanceSourceError` — source missing or a Level.
- `SceneInstanceCycleError` — source path appears in the resolution chain.
