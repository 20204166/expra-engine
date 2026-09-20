# Expra Filesystem and Asset Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a renderer-neutral hybrid filesystem and asset pipeline supporting logical resource IDs, project directories, package archives, user data, caching, dependencies, async loading, and export/runtime resolution.

**Architecture:** Logical IDs are the persisted identity. Explicit directory and archive mounts resolve those IDs with deterministic precedence. Core reads and caching remain renderer-neutral; renderer adapters and physical-path extraction are controlled boundaries. User data is a separate confined service.

**Tech Stack:** Python, `pathlib`, `zipfile`, dataclasses/protocols, existing `AppCoordinator`, pytest, mypy, pyright, Ruff.

---

## File Structure Map

Create focused modules:

- `src/expra_engine/filesystem/ids.py`: logical resource ID parsing and normalization.
- `src/expra_engine/filesystem/errors.py`: typed filesystem/package/dependency errors.
- `src/expra_engine/filesystem/mounts.py`: mount protocols, directory mounts, and archive mounts.
- `src/expra_engine/filesystem/resources.py`: resource metadata, handles, reads, and resolver.
- `src/expra_engine/filesystem/cache.py`: cache entries, invalidation, and disposal.
- `src/expra_engine/filesystem/dependencies.py`: dependency graph and cycle detection.
- `src/expra_engine/filesystem/service.py`: synchronous and async resource service.
- `src/expra_engine/filesystem/packages.py`: package manifest validation and safe extraction.
- `src/expra_engine/filesystem/user_data.py`: isolated application/game user storage.
- `src/expra_engine/filesystem/__init__.py`: public exports only.
- `tests/test_resource_ids.py`: ID and confinement contracts.
- `tests/test_resource_mounts.py`: directory/archive resolution and precedence.
- `tests/test_resource_service.py`: reads, cache, invalidation, and disposal.
- `tests/test_resource_packages.py`: manifests and extraction.
- `tests/test_user_data.py`: user-data confinement and atomic writes.

Modify existing integration points:

- `src/expra_engine/core/project.py`: expose project resource-root conventions without loading assets.
- `src/expra_engine/editor/assets.py`: attach logical IDs to browser entries while retaining display paths.
- `src/expra_engine/export/manifest.py`: collect resolved logical resources and provenance.
- `src/expra_engine/export/plan.py`, `exporter.py`, `packager.py`: route export asset collection through the resource service.
- `tests/test_project.py`, `tests/test_editor_assets.py`, and export tests: preserve existing behavior and add logical-ID coverage.

## Task 1: Resource Identity and Errors

**Files:** Create `ids.py`, `errors.py`, `__init__.py`; test `test_resource_ids.py`.

- [ ] Write failing tests for valid schemes, slash normalization, case rules, empty components, traversal, NUL bytes, drive prefixes, and project-relative conversion.
- [ ] Run `pytest tests/test_resource_ids.py -v`; confirm failures because the API is absent.
- [ ] Implement immutable `ResourceId` with `scheme`, optional namespace, normalized path, `parse`, `from_project_path`, and stable string conversion.
- [ ] Implement typed errors carrying operation, logical ID, and mount/package context without exposing sensitive absolute paths.
- [ ] Run the focused tests and Ruff.
- [ ] Commit only the identity/error files and tests.

## Task 2: Directory Mounts and Resolver

**Files:** Create `mounts.py`, `resources.py`; test `test_resource_mounts.py`.

- [ ] Write tests for confined directory reads, missing resources, metadata, read-only enforcement, mount precedence, equal-precedence conflicts, unmounting, and physical provenance.
- [ ] Run the focused tests to verify they fail.
- [ ] Implement `ResourceMount` protocol, `DirectoryMount`, `MountSpec`, `ResourceHandle`, and deterministic `ResourceResolver`.
- [ ] Use confined path joins and reject symlink escapes when resolving project resources.
- [ ] Run focused tests plus `git diff --check`.
- [ ] Commit the directory resolver slice.

## Task 3: Archive Mounts and Package Manifests

**Files:** Modify `mounts.py`; create `packages.py`; test `test_resource_packages.py` and extend `test_resource_mounts.py`.

- [ ] Write tests using temporary ZIP archives for safe members, traversal/absolute members, duplicate logical names, metadata, precedence, malformed manifests, and read-only behavior.
- [ ] Run focused tests to verify failure.
- [ ] Implement ZIP-backed mounts with validated member names and direct streaming/read access.
- [ ] Define package manifest dataclasses with identity, version, format version, resources, sizes, hashes, and dependencies.
- [ ] Validate manifest/resource agreement before mounting.
- [ ] Implement explicit hash-keyed extraction into a confined cache directory using atomic replacement.
- [ ] Run package and mount tests.
- [ ] Commit the archive/package slice.

## Task 4: Cache and Dependency Graph

**Files:** Create `cache.py`, `dependencies.py`; test `test_resource_service.py`.

- [ ] Write tests for no-cache/memory-cache behavior, content identity, invalidation by ID and mount, disposal hooks, dependency registration, missing dependencies, and cycles.
- [ ] Run focused tests to verify failure.
- [ ] Implement cache entries with ownership, content identity, explicit invalidation, and idempotent disposal.
- [ ] Implement directed dependency registration, reverse invalidation, cycle detection, and bounded traversal.
- [ ] Run focused tests and type checks for the new modules.
- [ ] Commit the cache/dependency slice.

## Task 5: Resource Service and Async Loading

**Files:** Create `service.py`; modify `resources.py` to expose the resolver read/stream primitives used by the service; test `test_resource_service.py`.

- [ ] Write tests for bytes/text/stream reads, metadata-only access, cache policies, cancellation, stale generations, and renderer-independent operation.
- [ ] Run focused tests to verify failure.
- [ ] Implement `ResourceService` over the resolver, cache, and dependency graph.
- [ ] Add async requests using the existing coordinator delivery and generation/cancellation contracts without importing Tk or renderer modules.
- [ ] Ensure mount removal invalidates associated cache entries and invokes cleanup.
- [ ] Run focused tests and the existing coordinator tests.
- [ ] Commit the service slice.

## Task 6: Separate User Data

**Files:** Create `user_data.py`; test `test_user_data.py`.

- [ ] Write tests for namespaced roots, safe relative paths, traversal/symlink escape rejection, atomic writes, reads, deletion, and separation from resource mounts.
- [ ] Run focused tests to verify failure.
- [ ] Implement `UserDataStore` with application and game/project namespaces, confined operations, and atomic writes using the existing persistence convention.
- [ ] Ensure errors do not include absolute user paths.
- [ ] Run focused tests.
- [ ] Commit the user-data slice.

## Task 7: Project and Editor Integration

**Files:** Modify `core/project.py`, `editor/assets.py`; update project/editor tests.

- [ ] Write tests proving project resources produce stable `assets://` IDs and editor entries retain display `Path` plus logical ID.
- [ ] Run focused tests to verify failure.
- [ ] Add project-root/resource-service construction without making `Project` own loaded values.
- [ ] Extend `AssetEntry` and scan normalization with logical IDs while preserving existing sorting, filtering, and save/open behavior.
- [ ] Route import/rename/delete references through logical IDs at the boundary.
- [ ] Run project/editor tests and the full non-UI suite.
- [ ] Commit integration changes.

## Task 8: Export and Runtime Integration

**Files:** Modify `export/manifest.py`, `export/plan.py`, `export/exporter.py`, `export/packager.py`; update export tests.

- [ ] Write tests for logical-ID collection, package resources, hashes, provenance, aliases, missing resources, dependency cycles, and runtime manifests without absolute development paths.
- [ ] Run focused export tests to verify failure.
- [ ] Change manifest entries to record logical ID, source provenance, size, hash, and destination path while preserving compatibility for existing project exports.
- [ ] Make export resolve through `ResourceService` and include transitive dependencies.
- [ ] Add directory/package runtime mount configuration and safe extraction only when a decoder requires a physical file.
- [ ] Run all export tests, the full suite, Ruff, mypy, pyright, and `git diff --check`.
- [ ] Commit the export/runtime slice.

## Task 9: Final Validation and Documentation

- [ ] Add public API documentation and examples for logical IDs, mounts, package creation, resource reads, and user data.
- [ ] Run the complete test suite and record the exact result.
- [ ] Run package/build validation and verify no development absolute paths enter exported manifests.
- [ ] Review all changes for renderer/UI imports in filesystem modules, accidental user-data exposure, and unstaged unrelated-file modifications.
- [ ] Update the design/spec status to implemented only after verification.
- [ ] Commit documentation and final validation changes.
