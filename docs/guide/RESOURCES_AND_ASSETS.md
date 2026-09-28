# Resources and Assets

The filesystem API uses logical IDs as stable resource names. Physical paths are
mount/extraction details and are never persisted as asset references.

## Logical IDs

```python
from expra_engine.filesystem import ResourceId

player = ResourceId.parse("assets://textures/player.png")
level = ResourceId.from_project_path("levels/intro.json")
```

Supported schemes: `assets`, `engine`, `package`, `user`. Package IDs include
the package identity (`package://demo/data/file.txt`). IDs reject traversal,
absolute paths, empty components, and host-specific separators.

## Mounts

```python
from pathlib import Path
from expra_engine.filesystem import (
    ArchiveMount, DirectoryMount, MountSpec, ResourceResolver,
)

project = DirectoryMount(
    Path("project/assets"),
    MountSpec(name="project", scheme="assets", precedence=10, read_only=False),
)
runtime_package = ArchiveMount(
    Path("demo.zip"),
    MountSpec(name="demo", scheme="package", namespace="demo"),
)
resolver = ResourceResolver([project, runtime_package])

handle = resolver.resolve(ResourceId.parse("assets://textures/player.png"))
```

Higher precedence wins; equal-precedence matches raise `DuplicateResourceError`.
Directory mounts may be writable (`read_only=False`); archive mounts are
read-only and validated on open.

## ResourceService

```python
from expra_engine.filesystem import ResourceService

resources = ResourceService(resolver)
data = resources.read_bytes("assets://textures/player.png")
text = resources.read_text("assets://levels/intro.json")
metadata = resources.metadata("assets://textures/player.png")
with resources.open_stream("assets://textures/player.png") as s:
    first = s.read(16)
```

Use `CachePolicy.MEMORY`, `NO_CACHE`, or `REFRESH` to override caching. `mount` /
`unmount` invalidate owned cache entries.

## Packages

A package is a ZIP containing `package.json` and exactly the declared resource
members, with matching hashes/sizes. Extract only when a tool needs a physical
file (confined to a hash-keyed cache, atomic replacement).

## User data

`UserDataStore` is separate from project/package resources, confined to
application/game namespaces, with atomic writes. See
[Persistence](PERSISTENCE.md).

## Project asset access

In a project, `project.resource_service()` builds the resource service over the
`assets/` directory, and `project.asset_id(path)` / `project.import_asset(...)`
manage assets.

## What not to do

- Absolute machine paths in asset references.
- Runtime directory scanning (use the resource service).
- Loading files outside the resource system.
- Treating user data as a resource-mount fallback.
