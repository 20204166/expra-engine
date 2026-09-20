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

## Running

```bash
pip install -e .
expra-editor
# or
python -m expra_engine
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
./scripts/build-wheel.sh
```

The build does not install the wheel. Use `EXPRA_VERSION_BUMP=patch|feature|minor|none`
to override automatic version selection.

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

## Threading invariant

**Tk owns widgets. Background work never touches widgets.**

Results from background tasks cross from worker threads through the
`AppCoordinator`/`UICoordinator` delivery path onto the Tk main thread.
No worker ever calls `widget.configure()` directly.

See `docs/THREADING.md` for details.

See `docs/FILESYSTEM.md` for the logical-ID, mount, resource-service, package,
and user-data APIs.
