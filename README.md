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
ruff check .
pyright
mypy --ignore-missing-imports src
```

## Threading invariant

**Tk owns widgets. Background work never touches widgets.**

Results from background tasks cross from worker threads through the
`AppCoordinator`/`UICoordinator` delivery path onto the Tk main thread.
No worker ever calls `widget.configure()` directly.

See `docs/THREADING.md` for details.
