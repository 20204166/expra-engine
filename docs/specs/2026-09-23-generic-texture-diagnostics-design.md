# Generic Texture Diagnostics Design

**Goal:** Make Expra's asset-ID-to-pixel path inspectable and reusable across
all game projects, while retaining Blacksite Relay as a project-level dogfood
integration test.

## Scope

The diagnostic slice covers one selected static sprite asset through:

1. `SpriteComponent.asset`
2. extracted `RenderItem.material.texture_id`
3. project resource resolution
4. resolved mount and physical path
5. byte read
6. backend PNG decode
7. texture cache key
8. backend texture metadata
9. renderer draw and non-transparent output pixels
10. optional editor image presentation

It does not add sprite tooling, thumbnails, alpha-aware selection, regions, or
another rendering implementation.

## Public API

Add `expra_engine.runtime.texture_diagnostics` with:

- `TextureDiagnosticStage`: an immutable stage result containing a stable stage
  name, success flag, and safe human-readable detail.
- `TextureDiagnosticReport`: an immutable report containing the requested asset
  ID, matched entity IDs, ordered stages, overall success, failed stage, and
  failure detail. Backend objects are not retained in the report.
- `diagnose_texture(project, scene, asset_id, *, context, pygame_module,
  image_master=None)`: orchestrates the existing resource provider, extractor,
  Pygame renderer, and optional editor bridge.

The function accepts a logical asset ID and a render context supplied by the
caller. It does not guess a camera or project root. Invalid arguments raise
normal validation errors. Resource, decode, renderer, and presentation errors
return a failed report with the exact failed stage.

## Data Flow

The diagnostic locates all scene entities whose `SpriteComponent.asset` matches
the requested logical ID, extracts the canonical frame, and selects only the
matching render items for the probe. It resolves and reads through
`project.resource_service()`, then passes those same bytes through the existing
`PygameResourceProvider`.

The selected item is rendered using the existing `PygameRenderer` onto an
alpha-capable surface. The report records decoded texture size, cache key,
backend texture type, renderer completion, and non-transparent pixel bounds.
When `image_master` is supplied, the same selected frame is passed through the
existing editor pixel bridge and the report records final image dimensions.

No second resolver, resource cache, texture cache, or renderer is introduced.

The runtime diagnostic module must not statically import editor/UI modules. The
optional editor bridge is loaded only when an `image_master` is supplied, so
Pygame runtime exports retain their existing UI-free dependency closure.

## Failure and Logging

The report is the machine-readable result for tests, CI, and future projects.
Existing `[Texture]` logs remain the human-readable runtime signal for resolve,
read, decode, missing-provider, renderer, incomplete-frame, and editor
presentation failures. A failed report is never considered a successful
fallback rectangle.

## Generic Test Fixture

Add a small real PNG under `tests/fixtures/` with stable dimensions and visible
non-transparent pixels. Add a test-only temporary-project factory that:

- creates a normal `Project` rooted under `tmp_path`;
- copies the real PNG into the project's `assets/` directory;
- writes a scene containing a `SpriteComponent` referencing its
  `assets://` logical ID; and
- returns the project, scene, and expected asset ID without Blacksite-specific
  names or paths.

The generic test asserts every report stage and verifies non-transparent output
pixels after backend rendering and editor presentation. Blacksite tests invoke
the same diagnostic API for the sprite assets discovered from its scene, while
remaining responsible for project-specific integration behavior such as EDIT,
PLAY, and movement.

## Verification

Run the generic texture diagnostic tests, Blacksite integration tests, the full
pytest suite, and the Xvfb editor suite. Run whitespace validation and focused
Ruff checks for changed implementation and test files.
