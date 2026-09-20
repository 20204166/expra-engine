# Expra Filesystem and Asset Pipeline Design

## Status

Implemented and validated.

## Goal

Provide one renderer-neutral filesystem and asset foundation for Expra projects,
runtime loading, packages, exports, editor browsing, and user data. The system
must support both ordinary directories and archive/package resources without
making physical paths the identity of a resource.

PPB, Ursina, and MiniPyEngine are reference sources for behaviors and edge
cases. Their global state, renderer coupling, and physical-path assumptions are
not adopted as architecture.

## Non-Goals

- Implement renderer-specific texture, mesh, audio, or shader decoding in the
  filesystem layer.
- Make user data writable through project or package resource APIs.
- Preserve arbitrary path traversal or platform-specific path semantics.
- Build a general-purpose virtual operating system filesystem.

## Architecture

The system is hybrid and layered:

1. **Resource identity** uses normalized logical IDs, for example
   `assets://textures/player.png` and `engine://fonts/default.ttf`.
2. **Mounts** provide read access to directory trees or archive/package files.
3. **Resolution** applies explicit mount precedence and returns a resource
   handle containing its logical ID, mount, physical provenance when available,
   size, and content identity.
4. **Resource access** exposes bytes, text, streams, metadata, and async
   loading without requiring a renderer or UI toolkit.
5. **Cache and dependency services** track loaded values, content hashes,
   dependencies, invalidation, and lifecycle cleanup.
6. **Adapters** convert resource bytes into renderer-owned objects. Adapters
   may use a physical path only when a third-party decoder requires one.
7. **Project, editor, and export integrations** use the same logical IDs and
   resolver rather than independently walking physical directories.

Physical `Path` values remain valid at controlled boundaries: project opening,
editor file dialogs, directory mounts, imports, exports, and the separate user
data API. They are not persisted as the canonical asset reference.

## Resource IDs

Resource IDs must:

- use a required lowercase scheme and normalized `/` separators;
- reject empty components, `.` and `..` traversal, absolute paths, drive
  prefixes, NUL bytes, and ambiguous separator forms;
- preserve a stable logical spelling independent of the host OS;
- distinguish project resources, engine resources, packages, and user data;
- support conversion from an editor-selected project-relative path;
- avoid silently resolving outside the mount root.

The initial schemes are `assets://`, `engine://`, `package://`, and
`user://`. Package IDs include an explicit package identity rather than relying
on whichever archive happens to be mounted first.

## Mounts and Precedence

Mounts are immutable after registration except for explicit unmount/remount
operations. Each mount declares:

- scheme and optional package identity;
- logical prefix;
- source kind: directory or archive/package;
- read-only or writable capability;
- precedence;
- lifecycle ownership.

Resolution is deterministic. A higher-precedence mount wins; equal-precedence
duplicates are an error rather than an arbitrary filesystem-order choice.
Directory mounts use confined path joins. Archive mounts validate member names
before exposing them and reject traversal, absolute members, duplicate logical
names, and unsafe extraction targets.

Project resources are read/write through project APIs. Package and engine
resources are read-only. User data is not a resource fallback and is accessed
through a separate storage service.

## Loading, Cache, and Dependencies

The core service supports:

- metadata lookup without decoding;
- byte and text reads;
- streaming for large resources where supported;
- synchronous access for deterministic callers;
- async access integrated with existing `AppCoordinator` generation and
  cancellation contracts;
- cache policies for no-cache, memory-cache, and refresh behavior;
- content identity based on size and SHA-256 or an equivalent stable digest;
- explicit invalidation by logical ID, mount, or content change;
- dependency registration for resources that reference other resources;
- cycle detection and bounded recursive dependency loading;
- cleanup hooks for values owning external resources.

The filesystem never assumes that a loaded value is renderer-safe to share.
Cache ownership and disposal are explicit, so renderer resources can be
released when a mount is removed or a cache entry is invalidated.

## Packages and Extraction

Packages are first-class read-only mounts. The first implementation should
support a standard archive format available in the Python runtime and define a
package manifest containing:

- package identity and version;
- exported logical resources;
- content hashes and sizes;
- optional dependency declarations;
- format/version metadata.

Package resources should be read directly when possible. Extraction is an
explicit operation for tools or decoders that require a physical file, and it
must use a confined cache directory keyed by package identity and content
hash. Extraction must be atomic, reject unsafe names, and never extract into
the project or user-data root implicitly.

## User Data

User data is deliberately separate from project assets and package resources.
The API provides an application-scoped root and namespaced game/project data,
with confined read/write operations, atomic writes, and safe filename/path
validation. User data is not included in project exports unless an explicit
export operation requests a copy.

## Project and Editor Integration

`Project` remains a lightweight metadata object. A project resource service is
constructed around its root and registers the project assets mount. Existing
editor scans can continue to enumerate physical directories, but their output
must carry a logical ID alongside the display `Path` so UI code does not make
physical paths persistent references.

Import, rename, delete, and save operations use project-relative logical IDs,
with overwrite confirmation and atomic persistence retained. Directory
watching or polling is an adapter concern; change events are translated into
logical invalidations before reaching the editor or runtime.

## Export Integration

Export collection resolves referenced logical IDs through the same resource
service. The export manifest records logical ID, source provenance, content
hash, size, and destination path. Duplicate content may be deduplicated while
preserving logical aliases. Missing resources, conflicting IDs, invalid
package manifests, and dependency cycles are build errors with actionable
diagnostics.

The exported runtime can use a directory mount, a package mount, or both. The
runtime manifest must not require the development machine's absolute paths.

## Error Model

Errors are typed and renderer-neutral. At minimum, distinguish:

- invalid resource ID;
- mount not found;
- resource not found;
- duplicate/conflicting resource;
- permission or capability failure;
- unsafe archive member or extraction target;
- malformed package manifest;
- dependency cycle or missing dependency;
- decode/adapter failure;
- cancellation and stale async result.

Errors should include the logical ID, operation, and relevant mount/package
identity without leaking sensitive absolute user-data paths.

## Testing Strategy

Tests are organized around contracts, not implementations:

- logical ID normalization and traversal rejection across platforms;
- directory and archive mount parity;
- precedence, duplicate detection, mount lifecycle, and read-only rules;
- package manifest validation and safe extraction;
- byte/text/stream reads and cache behavior;
- dependency graphs, cycles, invalidation, and disposal;
- async cancellation and stale-generation rejection;
- user-data confinement and atomic writes;
- export manifests, missing resources, aliases, hashes, and packaged runtime
  resolution;
- compatibility tests for existing project, editor, and export behavior.

The first implementation slices should be independently useful: resource IDs
and confinement, directory mounts, archive mounts, loading/cache/dependencies,
then project/editor/export integration.

## Open Design Defaults

Unless implementation research exposes a concrete compatibility issue, use:

- `zipfile` for the initial archive mount;
- SHA-256 for content identity and export verification;
- explicit mount registration rather than implicit global search;
- logical IDs as persisted references;
- project and package resources read through one resolver;
- user data through a separate service and namespace;
- renderer adapters above the core filesystem boundary.
