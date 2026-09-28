# Play vs Run Project

Two ways to execute a project, with different semantics.

## Editor Play (toolbar `▶`)

- Runs the engine **in-process** on the Tk thread via `RuntimePreviewLoop`
  (`~60 FPS` via `root.after(16, …)`).
- Deep-copies the edit scene (JSON round-trip) and plays that copy; the edit
  scene stays untouched. If a World is active, plays via
  `WorldStreamingSystem.runtime_scene`.
- The viewport switches to runtime rendering: no editor overlays, uses
  `scene.camera`, interpolation, animated-sprite players.
- **Stop** restores the edit scene exactly.

Play runs the **current scene/level/world** — it does not follow
`project.json`'s entrypoint.

## Run Project (toolbar `▶▶`)

- Launches the project's Python entrypoint (default `__main__.py`, or
  `project.entry_point`) **as a separate child process**
  (`subprocess.Popen`, `cwd=project.path`).
- Follows `project.json`'s `entrypoint` — so a World-entrypoint project starts
  from the World, and its `__main__.py` uses `run_project()` / `PygameRuntime`.
- The editor polls the process; Stop terminates it (escalating to kill).

Run Project executes the **whole game from its entrypoint** as shipped (closer
to an export), independent of whatever is open in the editor.

## Comparison

| | Play | Run Project |
|---|---|---|
| Process | in-editor | child process |
| Entrypoint | current document | `project.json` entrypoint |
| World entrypoint | yes (if world active) | yes (follows entrypoint) |
| Stop/restore | `engine.stop()` restores edit scene | process terminate; editor restores prior document |
| Headless/Tk | Tk thread | game runtime (no Tk) |
