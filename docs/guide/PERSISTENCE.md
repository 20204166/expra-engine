# Persistence

Three distinct kinds of state must not be confused:

| State | Where it lives | Lifetime |
|---|---|---|
| **Authored state** | `.pb` / `project.json` documents | edited by developer |
| **Runtime state** | in-memory engine/scene | a Play session |
| **Session state** | `WorldSessionState` / persistent actors | across Level travel within a session |
| **Save data** | `UserDataStore` | across app launches |

## Authored vs runtime vs session

- **Authored** documents are what the editor edits and saves (`.pb`).
- **Runtime** state is the live simulation (entity positions, behaviour
  instance state); it is discarded on Stop.
- **Session** state is opt-in and preserved only across Level travel within a
  World (via `WorldSessionStateComponent` and `WorldPersistentActorComponent`).
  It is **not** automatically saved to disk.

## User data (`UserDataStore`)

`filesystem/user_data.py` provides per-app/game namespaced storage with atomic
writes:

```python
from pathlib import Path
from expra_engine.filesystem import UserDataStore

user_data = UserDataStore(Path("user-data"))
user_data.write_text("settings.json", '{"volume": 80}')
user_data.write_bytes("save.bin", b"save", namespace="game")
settings = user_data.read_text("settings.json")
save = user_data.read_bytes("save.bin", namespace="game")
user_data.delete("settings.json")
```

Paths must be relative; traversal and symlink escapes out of the namespace are
rejected. User data is never a resource-mount fallback or export input unless
an export operation explicitly requests it.

## Saving a game

There is **no full save-game framework**. To persist progress, serialise your
own save data (dict/JSON) and write it through `UserDataStore`. For cross-Level
survival within a session, use the World session mechanism; for persistence
across launches, use `UserDataStore` explicitly.

## What not to save

- Live behaviour/module instances or closures.
- `entity_id`s as durable identity across app versions without care (they are
  stable within a document, but user data should carry its own keys).
- Materialized scene-instance children (regenerated on load).
