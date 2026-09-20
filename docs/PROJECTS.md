# Expra Game Projects

Expra projects are self-contained game workspaces. The project directory is the
source of truth for scenes, assets, scripts, input bindings, and export identity.

```text
MyGame/
  project.json
  scenes/main.json
  scripts/
  assets/
```

`Project.create(name, path)` creates this layout atomically, including a valid
starter scene. `Project.load(path)` accepts either the project directory or its
`project.json`. Existing manifests with only `name` and `scenes` remain valid;
they are treated as legacy schema 0. Current manifests use schema 1 and may
define `game_version`, `start_scene`, and `input`.

Scene and script references are project-relative (`project://scenes/...` and
`project://scripts/...`). No normal project operation depends on the process
working directory, so projects can be moved and reopened elsewhere.

The editor provides File -> New Project, Open Project, Close Project, New
Scene, and project-owned Save/Export actions. Editor preferences such as recent
projects and window geometry remain outside `project.json`.

Scripts are loaded by `ScriptRegistry` from the active project's `scripts/`
directory. Export uses the active project's root and game version; it does not
use the editor repository or current working directory as the game root.
