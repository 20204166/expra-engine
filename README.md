# Expra Engine

A game engine and editor with coordinated background work, deterministic runtime
state, and a renderer-neutral design language.

## Architecture

| Coordinator | Owns |
|---|---|
| `AppCoordinator` | Background work lifecycle, coalescing, cancellation |
| `ButtonCoordinator` | UI action dispatch, widget enable/disable |
| `UICoordinator` | Presentation commits, stale-render rejection, batching |
| `ComponentRefreshScheduler` | When periodic work runs |

## Engine Model

| Concept | Role |
|---|---|
| `Engine` | Runtime + editor state owner |
| `Project` | File structure, scene registry |
| `Scene` | Entity container, serialization |
| `Entity` | Named game object with components |
| `Component` | Data attached to an entity |
| `TransformComponent` | 2D position, rotation, scale |

## Editor Layout

```
+------------------------------------------------------+
| Menu / Toolbar                                       |
+------------+----------------------+------------------+
| Scene      |                      | Inspector        |
| Hierarchy  |      Viewport        |                  |
|            |                      |                  |
+------------+----------------------+------------------+
| Assets / Console / Status                            |
+------------------------------------------------------+
```

The editor's semantic design vocabulary is available without GUI dependencies
through `expra_engine.design`. The Tk-specific adapter remains under
`expra_engine.ui`; shipped games must not depend on Tk. See
`docs/GAME_UI_FUTURE.md` for the future renderer-backed game UI boundary.

## Running The Editor

```bash
pip install -e .
expra-editor
# or
python -m expra_engine
```

The editor uses Tk through `expra_engine.ui`. It is not the game runtime.

Game rendering is defined by the backend-neutral `Renderer` protocol in
`expra_engine.runtime.rendering`. The current Pygame adapter uses an
orthographic camera, viewport-aware culling, stable depth/layer ordering,
parent transform composition, render phases, and backend-neutral primitive and
material descriptors. These are 3D graphics principles applied to the 2D game
path; meshes, lighting, and perspective are not required by the sample yet.

Screen effects use the same renderer-neutral path. `BackBufferCopyComponent`
captures a viewport or transformed rectangle, while `ScreenTextureComponent`
consumes a named capture with nearest/linear filtering, optional mipmaps, UV
cropping, tint, opacity, and rotation. The runtime carries these operations in
an ordered `RenderFrame.submissions` stream; Pygame owns copied surfaces and
sampling, while the editor reports screen effects as unsupported preview data
instead of attempting fake pixel rendering. Capture surfaces remain
runtime-owned; only the renderer-neutral component requests are serialized.

## Running The Example Games

The repository includes several project-owned dogfood games. They exercise the
real editor, scene loader, scripts, renderer, physics, input, lifecycle, and
export paths rather than a test-only harness. Install the project dependencies
for source runs:

```bash
pip install -e .
```

### Neon Arena

Neon Arena is the renderer/runtime sample with legacy and scripted modes:

```bash
SDL_VIDEODRIVER=x11 python examples/neon_arena
```

To export a standalone Linux build with no Tk or editor runtime:

```bash
python -m expra_engine.export.cli examples/neon_arena \
  --target linux \
  --output "$PWD/builds" \
  --game-name Neon_Arena \
  --runtime-profile pygame \
  --no-bytecode
cd builds/Neon_Arena_linux
./Neon_Arena_debug.sh
```

The normal launcher is `Neon_Arena.sh`. The debug launcher writes `log.txt` and
returns the game's failure status. For deterministic headless validation, use
the opt-in smoke mode:

```bash
SDL_VIDEODRIVER=dummy EXPRA_SMOKE_FRAMES=60 \
  EXPRA_SMOKE_REPORT=smoke-report.json ./Neon_Arena_debug.sh
```

The smoke report confirms the bundled runtime started and rendered the exact
requested number of frames. Use `xvfb-run` instead of `SDL_VIDEODRIVER=dummy`
to exercise a real SDL window in CI or on a desktop without changing the game.

### Space Pong

Space Pong is the small editor/runtime acceptance project for generic scene
components, scripts, colliders, HUD layout, save/reopen, and export behavior:

```bash
SDL_VIDEODRIVER=x11 python examples/space_pong
PYTHONPATH=src python -m pytest -q tests/test_space_pong.py
```

### Blacksite Relay

Blacksite Relay is the larger combat dogfood project. It exercises sprite
resources, hierarchy, triggers, physics overlap/raycast queries, scripted input,
mission state, and a real asset-backed Pygame runtime. Controls are WASD or
arrow keys to move/aim, Space/F to fire, P to pause, and R to restart:

```bash
SDL_VIDEODRIVER=x11 python examples/blacksite_relay
```

Its Kenney Top-down Shooter assets are credited in
`examples/blacksite_relay/ASSET_CREDITS.md` and covered by the repository's
third-party notices.

To export either project, pass its directory to the existing exporter. For
example:

```bash
python -m expra_engine.export.cli examples/blacksite_relay \
  --target linux \
  --output "$PWD/builds" \
  --game-name Blacksite_Relay \
  --runtime-profile pygame \
  --no-bytecode
```

## Development

```bash
pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check src tests
pyright
mypy src tests
```

## Wheel Release

Builds automatically compare package inputs with the newest local wheel, bump
the Expra version when needed, refresh `dist/SHA256SUMS`, and verify the wheel:

```bash
EXPRA_VERSION_BUMP=auto ./scripts/build-wheel.sh
```

Validate the installed editor entry point in a clean virtual environment:

```bash
./scripts/smoke-installed-editor.sh
```

`auto` is the normal release mode: it selects `patch`, `feature`, `minor`, or
`none` from the package-input diff. Do not use `none` for a release that should
publish the current changes. The build does not install the wheel. Explicit
overrides are `EXPRA_VERSION_BUMP=patch|feature|minor|none`.

Install the latest built wheel outside the repository virtual environment:

```bash
./scripts/install-user.sh
```

Use `./scripts/install-user.sh --system` for a machine-wide install, or
`EXPRA_SYSTEM_PYTHON=/path/to/python` to select a specific system interpreter.
The install script verifies the wheel before installation and confirms the
installed `expra-editor` version afterward.

Install the latest published wheel directly from GitHub, with mandatory
SHA-256 verification:

```bash
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/20204166/expra-engine/main/scripts/install-online.sh | bash
```

Use `--system` for a machine-wide install, or `--base-url=URL` when mirroring
the wheel and `SHA256SUMS` to another location. Releases are published by
pushing a matching `vMAJOR.MINOR.PATCH.BUILD` tag.

On Windows PowerShell, use the adapted Expra online installer:

```powershell
irm https://raw.githubusercontent.com/20204166/expra-engine/main/install/install-online.ps1 | iex
```

It downloads the newest wheel named by `dist/SHA256SUMS`, verifies the digest,
bootstraps Python 3.12 through `winget` when needed, installs for the current
user, and verifies the installed version. Use `-System` with a downloaded copy
for a machine-wide install.

On Linux, the online installer uses an existing Python 3.12+ interpreter when
available. If none is available, it bootstraps `uv`, creates a managed Python
3.12 environment under `~/.local/share/expra-engine`, installs the verified
wheel there, and prints the launcher path. `--system` intentionally requires an
existing system Python.

## Threading invariant

**Tk owns widgets. Background work never touches widgets.**

Results from background tasks cross from worker threads through the
`AppCoordinator`/`UICoordinator` delivery path onto the Tk main thread.
No worker ever calls `widget.configure()` directly.

See `docs/THREADING.md` for details.

See `docs/GAME_EXPORT_FUTURE.md` for the runtime profile and export boundary.

See `docs/FILESYSTEM.md` for the logical-ID, mount, resource-service, package,
and user-data APIs.
