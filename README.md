# Expra Engine

A game engine and editor built on the proven coordinator architecture from System Analyzer.

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

## Threading invariant

**Tk owns widgets. Background work never touches widgets.**

Results from background tasks cross from worker threads through the
`AppCoordinator`/`UICoordinator` delivery path onto the Tk main thread.
No worker ever calls `widget.configure()` directly.

See `docs/THREADING.md` for details.
