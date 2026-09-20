# Filesystem and Asset Pipeline

The filesystem API uses logical IDs as stable resource names. Physical paths
are mount or extraction details and are not persisted as asset references.

## Logical IDs

Use `ResourceId.parse` for canonical IDs and
`ResourceId.from_project_path` for project-relative paths:

```python
from expra_engine.filesystem import ResourceId

player = ResourceId.parse("assets://textures/player.png")
level = ResourceId.from_project_path("levels/intro.json")

assert str(player) == "assets://textures/player.png"
assert str(level) == "assets://levels/intro.json"
```

The supported schemes are `assets`, `engine`, `package`, and `user`.
Package IDs include the package identity, for example
`package://demo/data/file.txt`. IDs reject traversal, absolute paths, empty
components, and host-specific separators.

## Directory and Archive Mounts

Mounts declare their logical scope and precedence. A higher precedence wins;
equal-precedence matches raise `DuplicateResourceError`.

```python
from pathlib import Path

from expra_engine.filesystem import (
    ArchiveMount,
    DirectoryMount,
    MountSpec,
    ResourceId,
    ResourceResolver,
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
print(handle.mount, handle.metadata.size, handle.metadata.content_hash)
```

Directory mounts can be writable when `read_only=False`:

```python
resolver.write(ResourceId.parse("assets://levels/intro.json"), b"{}")
```

Archive mounts are read-only and are validated when opened.

## ResourceService Reads

`ResourceService` provides renderer-neutral bytes, text, streams, and metadata.
It accepts either a `ResourceId` or its string form.

```python
from expra_engine.filesystem import ResourceService

resources = ResourceService(resolver)
data = resources.read_bytes("assets://textures/player.png")
text = resources.read_text("assets://levels/intro.json")
metadata = resources.metadata("assets://textures/player.png")

with resources.open_stream("assets://textures/player.png") as stream:
    first_bytes = stream.read(16)
```

Use `CachePolicy.MEMORY`, `NO_CACHE`, or `REFRESH` with `read_bytes` when the
default cache policy needs to be overridden. `mount` and `unmount` invalidate
owned cache entries and close mounts that provide `close()`.

## Package Creation and Extraction

A package is a ZIP archive containing `package.json` and exactly the declared
resource members. Manifest hashes and sizes must match the archive contents.

```python
import hashlib
import json
import zipfile
from pathlib import Path

payload = b"hello"
manifest = {
    "identity": "demo",
    "version": "1.0.0",
    "format_version": 1,
    "resources": [{
        "path": "data/file.txt",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "dependencies": [],
    }],
    "dependencies": [],
}

with zipfile.ZipFile("demo.zip", "w") as archive:
    archive.writestr("package.json", json.dumps(manifest))
    archive.writestr("data/file.txt", payload)
```

Extract only when a tool or decoder requires a physical file. Extraction is
confined to a hash-keyed cache and uses atomic replacement:

```python
from expra_engine.filesystem import ArchiveMount, MountSpec, ResourceId

mount = ArchiveMount(
    Path("demo.zip"),
    MountSpec(name="demo", scheme="package", namespace="demo"),
)
path = mount.extract(ResourceId.parse("package://demo/data/file.txt"), Path("cache"))
```

## User Data

`UserDataStore` is separate from project and package resources. It confines
operations to application and game namespaces and performs atomic writes.

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

User-data paths must be relative and cannot traverse or follow symlinks out of
their namespace. User data is never a resource-mount fallback or an export
input unless an explicit export operation requests it.
