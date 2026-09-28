# Scenes

A **Scene** is a reusable composition of entities: an ordered entity list, a
scene camera, and hierarchy/tag/query facilities. It is the basic building
block for gameplay and UI.

## What a Scene is

- An entity container with parent/child hierarchy, tags, and component queries.
- Serializable to `.scene.pb` (or legacy `.scene.json`).
- Instanceable via `SceneInstanceComponent` (see [Scene Instances](SCENE_INSTANCES.md)).

## When to use one

Use a Scene for a **reusable composition**:

- player HUD, enemy HUD, dialogue panel;
- a building, character, weapon, or reusable prop;
- a pause menu or skill tree.

## When NOT to use one

- Do not make a Scene a full open-world map — that's a World.
- Do not make a Scene the "playable place" directly — that's a Level (which is
  a Scene plus metadata).

## Core API

```python
from expra_engine.core.scene import Scene

scene = Scene("MyScene")                       # scene_id defaults to a fresh uuid4
entity = scene.create_entity("Player")         # constructs + registers
entity.add_component(TransformComponent())
scene.find_entity(entity.entity_id)
scene.get_entities_by_tag("enemy")
scene.get_entities_by_component(SpriteComponent)
```

Key methods (all in `core/scene/scene.py`):

| Method | Purpose |
|---|---|
| `create_entity(name)` / `add_entity(e)` | create / register an entity |
| `remove_entity(id, recursive=…)` | remove (optionally subtree) |
| `clone_entity(id)` | independent deep copy with fresh UUIDs |
| `transfer_entities_to(target)` | move entities to another Scene, preserving identity |
| `find_entity(id)` / `find_entity_by_name(name)` | lookup |
| `world_pose` / `world_transform(id)` | parent-composed transform |
| `get_entities(*, tag=…, component=…)` | filtered queries |
| `set_entity_parent(id, parent_id)` | re-parent with cycle guard |
| `walk_hierarchy` / `roots` / `children_of` | traversal |
| `to_dict` / `from_dict` | serialization |

## Serialization

`Scene.to_dict` emits the scene id, name, camera, and entities (each with
`entity_id`, `name`, `enabled`, `layer`, `parent_id`, `tags`, `components`).
`include_instance_content=False` omits scene-instance materializations.

## Entities

See [Entities and Components](ENTITIES_AND_COMPONENTS.md) for `Entity` and the
component reference.
