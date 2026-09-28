# Getting Started

## What Expra is

Expra Engine is a 2D game engine with an integrated editor. It has:

- a **document model** — projects, worlds, levels, scenes, entities, components;
- a **headless runtime** — deterministic fixed-step loop, behaviours, physics
  queries, 2D lighting, world streaming;
- a **Pygame renderer** (the current backend);
- a **Tk editor** for authoring documents and previewing gameplay;
- an **exporter** that bundles a project into a standalone build.

The editor is for authoring; shipped games never depend on Tk.

## Requirements

- Python **3.12+** with `venv` support.
- The editor needs Tk (usually bundled with Python; install `python3-tk` on
  Debian/Ubuntu if missing).
- The Pygame renderer needs `pygame` (pulled in automatically for source runs
  and Pygame exports).
- Normal mapping additionally needs `numpy` (optional).

## Install (development)

```bash
git clone <repo> && cd expra-engine
pip install -e .
```

## Launch the editor

```bash
expra-editor
# or
python -m expra_engine
```

A welcome dialog offers New Project / Open Project / recent projects.

## Create a project from the CLI

```bash
expra-new MyGame /path/to/workspace
```

This writes `project.json`, a starter scene, and a `__main__.py` launcher.

## First steps in the editor

1. **New Project** (File → New Project) — pick a name and location.
2. **Add an entity** — the toolbar "Add" button creates an entity with a
   `TransformComponent`. Use the Inspector to add components.
3. **Add a sprite** — Add Component → `sprite`, then set the asset to an
   `assets://…` texture you imported into `assets/`.
4. **Add a camera** — the scene has a default `Camera2D`; the editor draws its
   frame in the viewport. See [Camera](CAMERA.md).
5. **Add a behaviour** — create `scripts/player.py` with a `Behaviour`, then Add
   Component → `script` pointing at `project://scripts/player.py`.
6. **Add a light** — Add Component → `light_2d` on a lamp entity, plus a
   `canvas_modulate` to set a dark ambient baseline.

## Run it

- **Play** (toolbar `▶`) runs the current scene/level in-process in the editor.
- **Run Project** (toolbar `▶▶`) launches `project.json`'s entrypoint as a
  separate process. See [Play vs Run Project](PLAY_AND_RUN_PROJECT.md).

## Save

Editor File → Save writes the active document as a canonical `.pb` file. The
legacy `.json` format is a read-only import path.

## Export

```bash
python -m expra_engine.export.cli /path/to/MyGame \
  --target linux \
  --output ./builds \
  --game-name MyGame \
  --runtime-profile pygame
```

See [Export](EXPORT.md) for the full pipeline.

## Where to go next

- [End-to-End Tutorial](END_TO_END_TUTORIAL.md) — build a full game.
- [Document Model](DOCUMENT_MODEL.md) — understand scenes/levels/worlds.
- [Entities and Components](ENTITIES_AND_COMPONENTS.md) — every component.
