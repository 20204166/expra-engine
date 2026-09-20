# Game Export — Design and Status

## What Has Been Implemented

`expra_engine.export` is now a real subsystem, separate from `_release.py` and
the editor. It takes a user's game project and packages it for standalone
distribution.

### Implemented components

| Module | Responsibility |
|---|---|
| `export/plan.py` | `ExportPlan` — immutable, validated export configuration |
| `export/events.py` | `ExportProgressEvent`, `ExportPhase` — progress notifications |
| `export/manifest.py` | `AssetManifest`, `BuildManifest` — asset inventory and build record |
| `export/bytecode.py` | `BytecodeCompiler` — `.py` → `.pyc` with cancellation |
| `export/packager.py` | `WindowsPackager`, `LinuxPackager` — target-aware runtime install |
| `export/exporter.py` | `GameExporter` — pure orchestrator; no tkinter/ttkbootstrap |
| `export/verify.py` | `verify_export()` — fails closed; checks manifests |
| `export/cli.py` | CLI: `expra export <project> --target windows\|linux` |
| `editor/export_dialog.py` | Tkinter dialog wired via ButtonCoordinator → AppCoordinator |
| `runtime/pygame_runtime.py` | Non-Tk SDL/Pygame window, input, timing, and loop |
| `runtime/pygame_renderer.py` | Primitive 2D renderer and score/status HUD |
| `runtime/rendering.py` | Backend-neutral renderer protocol and 3D-ready frame contracts |

### Runtime boundary enforced

Exported games do NOT include:
- `expra_engine.editor`
- `expra_engine.ui`
- `tkinter`
- `ttkbootstrap`
- Ursina
- Panda3D

The `pygame` runtime profile stages only the engine core/runtime modules needed
by a game and installs Pygame into the target runtime. The editor-facing engine
wheel remains a separate distribution artifact and is not copied wholesale into
the game bundle.

The renderer contract is intentionally independent of Pygame. It provides an
orthographic camera, viewport mapping and culling, stable phase/layer/depth
ordering, parent transform composition, and primitive/material descriptors.
Pygame is currently the concrete adapter; another backend can implement the
same `Renderer` lifecycle without changing `Engine` or game logic.

### Atomic build contract

Export builds in a temp directory, calls `verify_export()`, then promotes to
the output directory. A failed build leaves the previous export intact.

### Cancellation

All pipeline stages check a `threading.Event`; progress is injected as
`Callable[[ExportProgressEvent], None]` — no polling, no global state.

### Target support

- **Windows**: downloads embeddable Python from python.org (cached), extracts
  to `runtime/python/`, patches `._pth` for site-packages, downloads
  target-architecture wheels via `pip download --platform win_amd64`.
- **Linux**: creates a venv under `runtime/`, installs packages into it.

Both targets produce normal and debug launchers (`.bat` / `.sh`).

### Tests (93 new + 40 from fork agent)

All tests use injected fakes or mock packagers. No internet required for
`pytest`. Covers: plan validation, manifest collection and round-trips,
bytecode compilation, packager launcher generation, verify_export failing
closed, full exporter end-to-end with mock packager, CLI argument parsing.

---

## What is still deferred

### Renderer seam

`ViewportPanel` (in `ui/viewport.py`) remains editor-preview-only. The
`Engine` is renderer-agnostic, while exported games can explicitly install the
Pygame/SDL adapter and `PygameRenderer`. The current renderer intentionally
supports primitive player/target shapes and HUD text; sprites, materials,
audio, meshes, lighting, perspective cameras, and a general asset/material
library remain future work. The backend-neutral renderer protocol itself is
implemented now so those features can be added without coupling the engine to
Pygame.

### Dependency resolution from pyproject.toml

The explicit `RuntimeProfile.PYGAME` currently resolves the Pygame dependency
and stages the runtime-only engine modules. General dependency resolution from
an arbitrary game `pyproject.toml` remains deferred; `plan.extra_packages`
continues to support additional packages.

### macOS target

Not implemented. Would need a framework Python bundle strategy.

### Single-file executable

PyInstaller / Nuitka integration is not implemented. Current output is a
directory with a launcher script, not a single `.exe`.

### Hot reload

If added, will use controlled asset invalidation rather than `exec`. No
global scene state mutation from exported games.

---

## Ownership boundaries (unchanged)

- `_release.py` owns the Expra **engine wheel** build. It is not touched by the
  export pipeline.
- `AppCoordinator` / `ButtonCoordinator` / `TkDeliveryQueue` remain the owners
  of background work and UI delivery.
- Security model, firewall configuration, HMAC secrets, fencing tokens — none
  of these are touched by the export pipeline.
- Exported games must have no Panda / Ursina / Tk game runtime dependency.
