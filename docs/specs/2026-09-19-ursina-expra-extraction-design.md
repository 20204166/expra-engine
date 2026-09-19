# Ursina to Expra Extraction Design

## Goal

Audit the supplied Ursina 8.2.0 source tree and incrementally adapt useful,
backend-neutral game UI and 2D runtime semantics into Expra without replacing
Expra's existing editor, runtime, entity/component, or release systems.

## Architecture

The work is split into independently testable phases. Phase 1 produces the
authoritative integration map and ownership decisions. Later phases add only
small Expra-native contracts where no existing owner exists, with pure logic
tested before any renderer or platform adapter. Editor Tk UI remains separate
from exported game runtime UI.

## Source and Constraints

- Source: `/home/btn17/Downloads/ursina-master`
- Ursina version: 8.2.0
- License: MIT, Copyright (c) 2020 Petter Amland
- Panda3D and Ursina must not become Expra dependencies.
- Existing Expra Entity/Component, PPB-derived runtime, coordinators, and
  wheel release system remain authoritative.
- No direct port of `camera.ui`, Panda Entity, global schedulers, `eval`,
  `exec`, mutable defaults, or synchronous UI-thread filesystem work.

## Phase Boundaries

1. Audit and contracts: classify requested sources A-E, map owners, document
   safety findings, rejected patterns, tests, and provenance.
2. Renderer-neutral UI: RectTransform, anchors, safe areas, nine-slice data,
   control state models, selection, progress, and focus seams.
3. Runtime interaction and timing: action maps, pointer/focus events,
   scaled/unscaled time, and deterministic timelines.
4. 2D runtime: sprite contracts, animation clips/states, smooth follow, and
   tilemap/autotile data.
5. Dialogue/editor/export references: typed dialogue, safe numeric editing,
   async asset-browser seams, platform contracts, and future export boundaries.

## Existing Owners

Reuse or extend `Entity`, `Component`, `Scene`, `Camera2D`, `RuntimeClock`,
`EventQueue`, `RuntimeSystem`, `Engine`, design tokens, `AppCoordinator`,
`UICoordinator`, editor persistence, and the existing release tooling. New
modules require a repository-wide ownership search and a failing behavior test
before production code.

## Testing

Use TDD for every implementation behavior: write a focused failing test, run
it to verify the expected failure, implement the smallest behavior, then run
focused and full validation. Prefer headless pure logic tests; use Tk only for
editor integration tests. Cover malformed, empty, boundary, disabled, pause,
resize, focus-loss, platform, and lifecycle cases relevant to each contract.

## Licensing

The audit map records Ursina source provenance. If substantial Ursina logic is
adapted, update `THIRD_PARTY_NOTICES.md` with the MIT copyright and notice.
Conceptual semantics and independently implemented algorithms will be clearly
distinguished from copied source.

## Success Criteria

- `docs/URSINA_INTEGRATION_MAP.md` classifies every required audit area.
- No existing Expra system is replaced.
- No Panda3D dependency is added.
- Game runtime does not require Tk.
- New behavior has edge-case tests and passes configured lint, type, full-test,
  package, and diff validation.
