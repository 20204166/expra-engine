# Game Export — Design and Status

## What has been implemented (Phase 14)

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

### Runtime boundary enforced

Exported games do NOT include:
- `expra_engine.editor`
- `expra_engine.ui`
- `tkinter`
- `ttkbootstrap`

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

`ViewportPanel` (in `ui/viewport.py`) renders game objects onto a Tk canvas for
editor preview only. The `Engine` itself is renderer-agnostic. A future
`GameRenderer` protocol will allow swapping in a real renderer for both
in-editor preview and exported games.

Until a renderer backend exists, the exported game cannot actually display
anything — the export pipeline packages and verifies structure but the game
itself will need its own renderer wiring.

### Dependency resolution from pyproject.toml

`GameExporter._resolve_packages()` currently uses only `plan.extra_packages`.
A complete implementation would call `uv pip compile pyproject.toml` to
auto-resolve the full dependency graph for the target platform.

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

