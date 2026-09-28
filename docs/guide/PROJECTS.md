# Projects

A project is a self-contained game workspace. Its directory is the source of
truth for documents, assets, scripts, input bindings, and export identity.

```text
MyGame/
  project.json
  __main__.py            # launcher (Run Project entrypoint)
  scenes/main.scene.pb   # starter scene (schema 1)
  scenes/                # (or legacy scenes/) scene + level documents
  worlds/                # .world.pb documents
  assets/                # textures, audio, fonts
  scripts/               # gameplay Python
```

## project.json

`Project` (`core/project.py`) fields and defaults:

| Field | Default | Notes |
|---|---|---|
| `name` | required | |
| `game_version` | `"0.1.0"` | |
| `schema_version` | `1` | legacy `0` still loads |
| `entrypoint` | `None` | canonical document entrypoint (Scene/Level/World) |
| `start_scene` | `None` | legacy alias for `entrypoint` (rejected if both set) |
| `entry_point` | `"__main__.py"` | Python script launcher target |
| `input` / `input_settings` | `None` | semantic input bindings |
| scene/level/world path registries | empty | populated as documents are saved |

## Creating and loading

```python
from expra_engine.core.project import Project

project = Project.create("MyGame", path)      # atomic; writes project.json + starter scene + __main__.py
project = Project.load(path)                  # path may be the dir or its project.json
```

`Project.create` is also exposed as `expra-new <name> [location]`.

## Document registries and entrypoint

- `project.register_scene_path` / `register_level_path` / `register_world_path`
  register documents. `scene_paths()`, `level_paths()`, `world_paths()` return
  them.
- `project.set_entrypoint(path)` sets the document a game starts from; the
  entrypoint may be a Scene, Level, or World.
- `Project` loads documents on demand; it does not keep all scenes in memory.

## Paths

Documents use project-relative paths with the `project://` scheme internally
(e.g. `project://scenes/main.scene.pb`). Both `scene/` and the legacy `scenes/`
folder are accepted. Scripts use `project://scripts/…`. No project operation
depends on the process working directory, so projects can be moved.

## Assets and input

- `project.asset_id(path)` and `project.import_asset(source, relative_path)`
  manage assets under `assets/`.
- `project.set_input_binding(action, physical)` stores semantic bindings
  (e.g. `"move_left"` → `"keyboard:left"`).
- `project.resource_service()` builds the renderer-neutral asset service.

## Saving

- `project.save()` writes `project.json`.
- `project.save_document(document, relative_path)` writes a canonical `.pb`.
- `project.save_scene` is the **legacy JSON** writer and is deprecated for editor
  use (it refuses to save a Level).

## Migration

`project.migrate_to_protobuf()` converts legacy `.json` documents to `.pb` and
reports the new paths.
