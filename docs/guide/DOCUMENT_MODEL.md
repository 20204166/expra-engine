# Document Model

Expra's authored content is a hierarchy of documents. Each document is a typed,
deterministic object graph.

```
Project
 └── World (geography / connectivity / residency)
       ├── LevelDescriptor → Level (.level.pb)
       ├── WorldConnection
       └── WorldStreamingSettings
 └── Level  →  Scene  →  Entity  →  Component
```

## The five document concepts

| Concept | What it is for | What it is NOT |
|---|---|---|
| **Project** | The whole game: metadata, document registries, entrypoint, asset root. | NOT a level manifest or a runtime state holder. |
| **World** | Geography, connectivity between Levels, residency, travel. | NOT a giant Scene; it owns no entity graph. |
| **Level** | A playable place: a Scene plus level metadata (bounds, spawn, camera). | NOT a reusable prefab; not an open-world map by itself. |
| **Scene** | A reusable composition of entities. | NOT a full map; not tied to world geography. |
| **Entity** | A named object with components, tags, a parent. | NOT persistent identity (use a persistent actor for that). |
| **Component** | Typed data attached to an entity. | NOT a runtime system; it is data only. |

### Relationship of Level to Scene

`Level` **is a** `Scene` (`class Level(Scene)`). A Level reuses the full Scene
entity graph (hierarchy, transforms, components, rendering, physics) and adds a
`LevelMetadata` payload and `DocumentKind.LEVEL`. There is no `LevelEntity` or
`LevelComponent` type — enemies, walls, and props are ordinary entities.

### Relationship of World to everything else

`World` is a frozen dataclass holding `LevelDescriptor`s, `WorldConnection`s,
`WorldStreamingSettings`, and metadata. It is **not** a `Scene` and never owns
entities. `Project.load_world` loads a World without loading its Level files.

## Document kinds and file extensions

`DocumentKind` (`core/document_kind.py`) is a `StrEnum`:

| Kind | value | canonical extension | legacy extension |
|---|---|---|---|
| Scene | `"scene"` | `.scene.pb` | `.scene.json` |
| Level | `"level"` | `.level.pb` | `.level.json` |
| World | `"world"` | `.world.pb` | `.world.json` |

`project.json` is the project manifest (not a document-kind file).

## JSON and Protobuf are ONE document

`.json` and `.pb` are **two representations of the same document**, not two
separate documents. There is no sidecar.

- **Developers edit** the in-memory model through the editor. The editor saves
  the canonical **`.pb`** form. `Project.save_document` writes `.pb` only and
  never writes a JSON sidecar.
- **The runtime loads** `.pb` (or legacy `.json`, read-only).
- **Legacy `.json`** is a read-only import path: `save_document` refuses to
  write it.

Conversion pipeline (`core/scene/document_codec.py`):

```
model → to_dict()  →  encode_protobuf()  →  bytes (.pb)
bytes → parse_protobuf() → protobuf_to_document_data() → from_document_data() → model
legacy .json → decode_json_payload() → from_document_data() → model
```

`encode_protobuf` uses `SerializeToString(deterministic=True)` for byte-stable
output. The wire format is a `DocumentEnvelope` with a `oneof { scene, level,
world }` (`schemas/level.proto`).

### schema_version and document_kind

- `schema_version` is `1` for projects and documents. Documents reject values
  outside `1`; `World` requires exactly `1`.
- `document_kind` selects the envelope branch and validates the file extension.

## Save / reopen

- **Save**: `Project.save_document(document, relative_path)` validates the kind
  vs extension, encodes to PB, and writes atomically. Scene documents serialize
  with `include_instance_content=False` (scene-instance materializations are
  regenerated on load, never stored).
- **Reopen**: `Project.read_document` reads bytes; `.pb` → protobuf path, `.json`
  → JSON path, then constructs the model and (for Scenes) resolves scene
  instances recursively.

## Unknown components and fields

- An **unknown component type** on load is preserved as an `OpaqueComponent`
  that keeps the original payload verbatim — so opening a newer document in an
  older engine doesn't drop data.
- A **known component type that fails to deserialize** raises an error.
- **Unknown fields** inside a known component are silently ignored.
- A malformed script component is preserved as `UnresolvedScriptComponent`
  (type `"missing_script"`).

## What never to edit by hand

- `.pb` files — treat them as opaque binary output.
- `project.json` internals you don't understand — use the editor/CLI.
- Anything that regenerates on load (scene-instance materializations).
