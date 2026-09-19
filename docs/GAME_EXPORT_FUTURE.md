# Game Export — Future Work

## What the engine wheel contains

The `expra-engine` wheel ships:

- **Core runtime**: Engine, Project, Scene, Entity, Component, TransformComponent
- **Coordinators**: AppCoordinator, ButtonCoordinator, UICoordinator, ComponentRefreshScheduler
- **Editor shell**: EditorWindow, all panels (hierarchy, viewport, inspector, console, toolbar)
- **Editor utilities**: TkDeliveryQueue, persistence, instance_lock, EditorPreferences
- **Observability**: ObservabilityWatcher
- **CLI entry point**: `expra-editor` (launches the editor)

The wheel is an **editor tool**, not a standalone game runtime.

## What "game export" would mean

A future game export feature would take a user's project (scenes, assets, scripts) and produce a **standalone executable** that runs without the editor:

1. **Stripped runtime** — editor panels, coordinators, delivery queue stripped; only Engine + core + user scenes remain
2. **Bundled assets** — user art, audio, and scene JSON bundled alongside the runtime
3. **Standalone packaging** — using PyInstaller or Nuitka to produce a single executable
4. **Platform targets** — Linux AppImage, Windows `.exe`, macOS `.app`

## Why it is not implemented yet

Game export requires:
- A defined project format (file layout, asset pipeline, scene references)
- A stripped runtime mode (no Tk, no editor, headless or custom renderer)
- A real renderer seam — `ViewportPanel` is an editor-only Tk preview; a
  production renderer is needed before export makes sense
- Build tooling for PyInstaller/Nuitka integration

These are Phase N (post-editor) concerns.  Export cannot be done correctly
until the editor project format is stabilised and a renderer decision is made.

## The renderer seam

`ViewportPanel` (in `ui/viewport.py`) renders game objects onto a Tk canvas for
editor preview only. The `Engine` itself has no renderer
dependency — it is renderer-agnostic by design.  A future `GameRenderer`
protocol will allow swapping in a real renderer for both in-editor preview
and exported games without changing the engine core.
