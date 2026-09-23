# Screen-Texture Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the supplied screen-texture contracts, ordered render plan,
and Pygame pixel pipeline into Expra without breaking ordinary rendering,
serialization, editor preview, legacy rendering, or export.

**Architecture:** Keep `RenderFrame.items` as the ordinary draw contract and add
an empty-default `submissions` stream containing ordinary items plus neutral
screen-effect markers when effects exist. `render_extractor` remains the only
scene extraction owner; `RenderPlanBuilder` orders the stream; `PygameRenderer`
delegates effect execution to `PygameScreenPipeline` while retaining all
ordinary draw code.

**Tech Stack:** Python, dataclasses, pytest, injected Pygame-like surfaces,
existing Scene/Entity/component registry, Tk editor preview, Expra exporter.

---

## File Map

- Modify `src/expra_engine/runtime/screen_texture.py` for canonical components,
  neutral requests, and effect markers.
- Delete `src/expra_engine/runtime/back_buffer_copy.py` after its tests migrate
  to the canonical module.
- Modify `src/expra_engine/runtime/render_pipeline.py` for frame conversion,
  stable effect ordering, and requirement metadata.
- Modify `src/expra_engine/runtime/rendering.py` for additive frame capability
  fields and `RenderFrame.submissions`.
- Modify `src/expra_engine/runtime/render_extractor.py` for effect extraction.
- Modify `src/expra_engine/runtime/pygame_screen_pipeline.py` only where
  backend/lifecycle edge cases require integration-compatible behavior.
- Modify `src/expra_engine/runtime/pygame_renderer.py` to execute plans while
  delegating ordinary drawing to its existing logic.
- Modify `src/expra_engine/runtime/project_runner.py` to carry submissions.
- Modify `src/expra_engine/runtime/__init__.py` to expose the integrated public
  runtime contracts.
- Modify `src/expra_engine/core/component.py` for registrations and Inspector
  schemas.
- Modify `src/expra_engine/ui/viewport.py` for explicit unsupported-preview
  effect reporting without fake Tk pixel rendering.
- Modify export tests to prove runtime staging already includes the three
  modules; do not add a second dependency scanner.
- Modify `tests/test_back_buffer_copy.py`,
  `tests/test_screen_texture.py`, `tests/test_render_pipeline.py`,
  `tests/test_pygame_screen_pipeline.py`, and existing component/extractor,
  renderer, editor, and export tests with regression coverage.
- Create `docs/specs/2026-09-22-screen-texture-integration-design.md` and keep
  `docs/plans/2026-09-22-screen-texture-integration.md` as uncommitted design
  artifacts because the user prohibited commits.

## Execution Rules

- Use TDD for every production behavior: add one focused failing test, run it,
  implement the smallest passing change, then run the focused regression set.
- Do not weaken supplied assertions. Migrate old duplicate tests to the
  canonical module rather than preserving duplicate production classes.
- Do not import Pygame from `rendering.py`, `render_pipeline.py`, or
  `screen_texture.py`.
- Do not serialize `RenderFrame.submissions`, plans, operations, snapshots, or
  Pygame surfaces.
- Do not commit or push.

### Task 1: Canonicalize Screen-Texture Contracts

**Files:**
- Modify: `src/expra_engine/runtime/screen_texture.py`
- Delete: `src/expra_engine/runtime/back_buffer_copy.py`
- Modify: `tests/test_back_buffer_copy.py`
- Modify: `tests/test_screen_texture.py`

- [x] **Step 1: Migrate the duplicate tests to the canonical module**

Replace imports from `expra_engine.runtime.back_buffer_copy` with imports from
`expra_engine.runtime.screen_texture`. Keep the test file and its coverage, but
assert the canonical request shape: `BackBufferCopyRequest` must include a
non-empty `entity_id`, named `capture_id`, mode, resolved `Transform`, and
unclamped `Rect`. Move disabled-component behavior to an assertion that no
effect marker is emitted by the extractor; keep disabled-mode validation on the
canonical request.

- [x] **Step 2: Run the migrated contract tests and confirm the expected red state**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_back_buffer_copy.py tests/test_screen_texture.py
```

Expected: the migrated tests fail first because `RenderEffect` and the new
frame/planner adapter are not yet present; this confirms the new assertions are
testing missing integration behavior rather than passing immediately.

- [x] **Step 3: Complete validation in `screen_texture.py`**

Preserve the supplied enums and component fields. Ensure constructors reject
empty `capture_id`, unsupported enum values, non-finite dimensions/LOD, UV
rectangles outside `[0, 1]`, invalid opacity, and disabled capture requests.
Add a frozen marker with this exact shape:

```python
@dataclass(frozen=True)
class RenderEffect:
    request: BackBufferCopyRequest | ScreenTextureDrawRequest
    phase: RenderPhase
    layer: int
```

Export `RenderEffect` from `__all__`. It carries no surface, plan, or backend
object.

- [x] **Step 4: Run the focused contract suite to green**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_back_buffer_copy.py tests/test_screen_texture.py
```

Expected: all canonical contract, validation, serialization-intent, and
backend-neutral tests pass.

- [x] **Step 5: Remove the obsolete duplicate module**

Delete `src/expra_engine/runtime/back_buffer_copy.py` only after the migrated
tests import the canonical module and a repository search confirms no remaining
production import references it.

### Task 2: Register Components and Preserve Scene Data

**Files:**
- Modify: `src/expra_engine/core/component.py`
- Modify: `src/expra_engine/runtime/screen_texture.py`
- Modify: `tests/test_component_schema.py`
- Modify: `tests/test_render_extractor.py`
- Modify: `tests/test_scene.py`
- Create: `tests/test_screen_texture_integration.py`

- [x] **Step 1: Add failing registration and full-scene round-trip tests**

Add tests that call `component_from_dict()` for both types, inspect
`component_type_spec()`, and round-trip a JSON scene containing both components:

```python
def test_screen_components_register_with_all_serialized_fields():
    assert component_type_spec("back_buffer_copy").cls is BackBufferCopyComponent
    assert component_type_spec("screen_texture").cls is ScreenTextureComponent
    assert tuple(field.name for field in component_type_spec("back_buffer_copy").fields) == (
        "copy_mode", "rect", "capture_id", "layer", "phase", "enabled"
    )
    assert tuple(field.name for field in component_type_spec("screen_texture").fields) == (
        "capture_id", "uv_rect", "width", "height", "filter", "lod", "tint",
        "opacity", "layer", "phase", "visible", "enabled"
    )

def test_screen_components_survive_full_scene_json_round_trip():
    scene = Scene("effects", scene_id="scene-1")
    entity = scene.create_entity("portal", entity_id="entity-1")
    entity.add_component(BackBufferCopyComponent(copy_mode="viewport", capture_id="portal"))
    entity.add_component(ScreenTextureComponent(capture_id="portal", filter="linear_mipmap"))
    restored = Scene.from_dict(json.loads(json.dumps(scene.to_dict())))
    assert restored.to_dict() == scene.to_dict()
```

Run the two new tests with `PYTHONPATH=src pytest -q`; expected failure is
unknown component type or missing schema metadata.

- [x] **Step 2: Add guarded canonical registration**

Add `_register_screen_components()` beside the existing visual registration
helpers. Register both classes in `_COMPONENT_REGISTRY` and install
`ComponentTypeSpec` values with these metadata constraints:

```python
PropertyDescriptor("copy_mode", "Copy Mode", str, "rect", enum_values=("disabled", "rect", "viewport"))
PropertyDescriptor("rect", "Rect", tuple, (-100.0, -100.0, 200.0, 200.0), tuple_length=4)
PropertyDescriptor("capture_id", "Capture ID", str, "screen")
PropertyDescriptor("phase", "Phase", str, "opaque", enum_values=("opaque", "transparent", "overlay"))
PropertyDescriptor("filter", "Filter", str, "linear", enum_values=("nearest", "linear", "nearest_mipmap", "linear_mipmap"))
PropertyDescriptor("uv_rect", "UV Rect", tuple, (0.0, 0.0, 1.0, 1.0), tuple_length=4)
PropertyDescriptor("width", "Width", float, 1.0, minimum=0.0)
PropertyDescriptor("height", "Height", float, 1.0, minimum=0.0)
PropertyDescriptor("lod", "LOD", float, 0.0, minimum=0.0)
PropertyDescriptor("opacity", "Opacity", float, 1.0, minimum=0.0, maximum=1.0)
```

Include `layer`, `tint`, `visible`, and `enabled` descriptors with their
constructor defaults. Call the helper from `component_from_dict()` and
`registered_component_types()`, and invoke it from `screen_texture.py` after
module definitions so direct schema lookup works after importing the canonical
module.

- [x] **Step 3: Run component and scene tests to green**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_screen_texture_integration.py tests/test_component_schema.py tests/test_scene.py tests/test_render_extractor.py
```

Expected: registration, metadata, malformed enum/empty ID validation, disabled
state, and Scene -> Entity -> JSON -> Scene round trips pass without serializing
any request, operation, plan, or surface object.

### Task 3: Add the Additive Frame and Plan Seam

**Files:**
- Modify: `src/expra_engine/runtime/rendering.py`
- Modify: `src/expra_engine/runtime/render_pipeline.py`
- Modify: `tests/test_render_pipeline.py`
- Create: `tests/test_render_frame_submissions.py`

- [x] **Step 1: Add failing frame-seam tests**

Add tests proving old construction remains valid and the new stream is runtime
only:

```python
def test_render_frame_defaults_to_empty_submissions():
    frame = RenderFrame()
    assert frame.items == ()
    assert frame.submissions == ()
    assert frame.submissions == ()

def test_plan_builder_accepts_items_and_effects_in_one_stable_stream():
    builder = RenderPlanBuilder.from_frame(
        RenderFrame(
            items=(item("draw"),),
            submissions=(
                item("draw"),
                RenderEffect(
                    BackBufferCopyRequest("copy", "screen", BackBufferCopyMode.VIEWPORT),
                    RenderPhase.OPAQUE,
                    0,
                ),
            ),
        )
    )
    assert [type(op) for op in builder.operations] == [DrawItemOp, CaptureScreenOp]
```

Run the new file. Expected failure is the absent `submissions` field and absent
`RenderPlanBuilder.from_frame()` method.

- [x] **Step 2: Add the neutral frame field and builder conversion**

Add this field at the end of `RenderFrame` so positional callers retain their
existing meaning:

```python
submissions: tuple[object, ...] = ()
```

Normalize it to a tuple in `__post_init__`. In `RenderPlanBuilder`, add
`from_frame(frame, context=None)` as a classmethod. Iterate
`frame.submissions or frame.items` in tuple order. For each `RenderItem`, call
`add_item`; for each `RenderEffect`, route `BackBufferCopyRequest` to
`add_capture` and `ScreenTextureDrawRequest` to `add_screen_texture`, using the
marker phase/layer and the tuple index as `insertion_index`. With a context,
skip ordinary items for which `item.is_visible(context)` is false; never skip
effect markers because backend clipping owns capture bounds.

- [x] **Step 3: Correct planner state transitions with focused tests**

Extend `tests/test_render_pipeline.py` for equal phase/layer/depth stability,
capture/draw/capture/draw ordering, independent named slots, first-consumer
automatic capture, non-mipmap consumers, mipmap reuse, and recapture mip
invalidation. Assert that every operation's `order` is nondecreasing and that
automatic capture uses the consumer's named slot and occurs immediately before
that consumer.

Preserve the supplied `RenderPlanBuilder` methods and make `from_frame()` a
thin adapter. Explicit capture must set that slot's mip state to false;
automatic capture must do the same; a later mipmapped consumer inserts exactly
one `GenerateScreenMipmapsOp` until the next capture.

- [x] **Step 4: Run the neutral planner suite to green**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_render_frame_submissions.py tests/test_render_pipeline.py
```

Expected: all operation ordering, auto-capture, named-slot, and mip-state tests
pass without importing Pygame.

### Task 4: Extract Effects Through the Canonical Scene Boundary

**Files:**
- Modify: `src/expra_engine/runtime/render_extractor.py`
- Modify: `src/expra_engine/runtime/screen_texture.py`
- Modify: `tests/test_render_extractor.py`
- Create: `tests/test_screen_texture_extraction.py`

- [x] **Step 1: Add failing extraction tests**

Create a scene with a background primitive, a `BackBufferCopyComponent`, a later
primitive, and a `ScreenTextureComponent`. Assert that `frame.items` contains
only the ordinary visual items, while `frame.submissions` preserves all four
events in entity/component insertion order. Add tests that disabled entities,
disabled components, hidden screen textures, and malformed effects produce no
effect marker.

```python
def test_extractor_interleaves_visuals_and_screen_effects_without_polluting_items():
    scene = Scene("effects")
    first = scene.create_entity("first", entity_id="first")
    first.add_component(PrimitiveComponent("rectangle"))
    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    second = scene.create_entity("second", entity_id="second")
    second.add_component(PrimitiveComponent("rectangle"))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(ScreenTextureComponent())

    frame = extract_render_frame(scene)

    assert [item.key for item in frame.items] == ["first", "second"]
    assert [getattr(entry, "request", entry).entity_id for entry in frame.submissions] == [
        "first", "capture", "second", "consumer"
    ]
```

Run the new test. Expected failure is an empty or absent submissions stream.

- [x] **Step 2: Emit canonical effect markers**

Import both screen component classes and `RenderEffect`. During the existing
entity/component loop, append each accepted ordinary `RenderItem` to both
`items` and a local `submissions` list. For a valid enabled
`BackBufferCopyComponent`, append a `BackBufferCopyRequest` using the entity ID,
capture ID, mode, resolved transform, and serialized local rect. For a valid
enabled and visible `ScreenTextureComponent`, append a
`ScreenTextureDrawRequest` using the entity ID, capture ID, resolved transform,
dimensions, UV, filter, LOD, tint, and opacity. Use `entity.layer + component.layer`
and the component phase for each marker.

Return `RenderFrame(tuple(items), elapsed=elapsed, modulation=modulation,
submissions=tuple(submissions) if any_effect else ())`.
This keeps ordinary scenes on the existing renderer path while preserving the
full mixed stream whenever an effect is present. Continue catching the existing
malformed-component exceptions and never traverse hierarchy separately in the
backend.

- [x] **Step 3: Verify transform, order, and modulation compatibility**

Add tests for translated/scaled/rotated entities, parent-composed transforms,
interpolated transforms, equal ordering keys, nonzero entity/component layers,
all render phases, and CanvasModulate. Assert the effect request transform is
the same resolved world transform that ordinary extraction uses, and that
`frame.modulation` remains the existing single resolved value.

- [x] **Step 4: Run extraction regressions to green**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_screen_texture_extraction.py tests/test_render_extractor.py tests/test_transform_interpolation.py tests/test_transform_interpolation_runtime.py tests/test_canvas_effects.py
```

Expected: ordinary item ordering and modulation tests remain green, and the
new mixed submission tests pass.

### Task 5: Validate and Harden the Pygame Screen Pipeline

**Files:**
- Modify: `src/expra_engine/runtime/pygame_screen_pipeline.py`
- Modify: `tests/test_pygame_screen_pipeline.py`

- [x] **Step 1: Add failing backend edge-case tests**

Extend the supplied fake surfaces with pixel/content markers and add tests for:

```python
def test_capture_stores_a_copy_and_does_not_alias_source():
    source = _Surface((8, 4))
    pipeline = PygameScreenPipeline(_Pygame())
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    pipeline.execute(
        builder.build(),
        surface=source,
        context=RenderContext(Viewport(0, 0, 8, 4), OrthographicCamera(width=8.0, height=4.0)),
        draw_item=lambda item, target: None,
    )
    assert pipeline.snapshot("screen").base is not source

def test_missing_backend_operation_is_explicit():
    pygame = SimpleNamespace(transform=SimpleNamespace())
    pipeline = PygameScreenPipeline(pygame)
    with pytest.raises(UnsupportedScreenPipelineFeature):
        pipeline._scale(_Surface((2, 2)), (4, 4), linear=False)
```

Also cover source non-mutation after tint, UV crop bounds, nearest versus
smooth scaling, mip LOD clamping, 1x1 termination, missing capture, rotated
blit, opacity/tint, completely outside clipping, nonzero viewport origin, and
`clear()` removing every named slot.

- [x] **Step 2: Run backend tests to establish exact failures**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_pygame_screen_pipeline.py
```

Expected: only newly added assertions fail before integration hardening; the
supplied 6 backend tests remain green.

- [x] **Step 3: Keep backend ownership narrow while fixing edge behavior**

Preserve the supplied executor shape. `_capture()` must calculate viewport or
four-corner projected RECT bounds, clip them to both the active viewport and
surface dimensions, call `subsurface(int_rect).copy()`, and replace the named
snapshot. `_generate_mipmaps()` must repeatedly halve each dimension to one
pixel using `smoothscale()`. `_draw_screen_texture()` must fail explicitly for
missing captures or unavailable crop/scale/rotate/blit operations, copy before
tinting, crop normalized UVs, select and clamp mip LOD, scale with `scale()` or
`smoothscale()`, rotate by entity degrees minus camera radians converted to
degrees, and blit the sampled result centered at the projected destination.

Do not add ordinary primitive, text, sprite, nine-slice, or modulation logic to
this module.

- [x] **Step 4: Run backend tests to green**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_pygame_screen_pipeline.py
```

Expected: all supplied and new capture, sampling, mipmap, error, clipping, and
lifecycle tests pass.

### Task 6: Execute Ordered Plans Through PygameRenderer

**Files:**
- Modify: `src/expra_engine/runtime/rendering.py`
- Modify: `src/expra_engine/runtime/pygame_renderer.py`
- Modify: `src/expra_engine/runtime/pygame_runtime.py`
- Modify: `tests/test_pygame_renderer.py`
- Modify: `tests/test_pygame_runtime.py`

- [x] **Step 1: Add failing capability and integration tests**

Add neutral capability defaults and Pygame assertions:

```python
def test_default_capabilities_do_not_claim_screen_support():
    capabilities = RendererCapabilities()
    assert not capabilities.screen_capture
    assert not capabilities.screen_texture
    assert not capabilities.screen_texture_mipmaps

def test_renderer_executes_capture_at_ordered_point_and_reuses_draw_logic():
    scene = Scene("effects")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent("rectangle"))
    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    later = scene.create_entity("later", entity_id="later")
    later.add_component(PrimitiveComponent("rectangle"))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(ScreenTextureComponent())
    frame = extract_render_frame(scene)
    renderer = PygameRenderer(_FakePygame(_FakeFont()), _Surface())
    renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
    renderer.render(frame)
    assert renderer.surface.subsurfaces == [(0, 0, 100, 100)]
    assert len(renderer.surface.blits) == 1
```

Add a draw-event log to the fake backend so the test proves the background draw
occurs before `subsurface`, the sampled draw occurs after it, and the later
ordinary item occurs in its planned position.

- [x] **Step 2: Run renderer tests and observe the red state**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_pygame_renderer.py tests/test_pygame_runtime.py
```

Expected: capability attributes and ordered screen execution are absent while
existing ordinary renderer tests remain green.

- [x] **Step 3: Add neutral capability fields**

Append these defaults to `RendererCapabilities`:

```python
screen_capture: bool = False
screen_texture: bool = False
screen_texture_mipmaps: bool = False
```

Initialize one `PygameScreenPipeline` in `PygameRenderer.__init__`. Set the
three fields from actual injected backend method availability: capture requires
surface `subsurface` and `copy`, screen sampling requires crop/scale/blit
operations, and mipmaps additionally require `transform.smoothscale`. A backend
with absent operations must report false rather than relying on a later error.

- [x] **Step 4: Refactor ordinary item drawing into one callback**

Extract the current per-item body from `PygameRenderer.render()` into a private
method with this contract:

```python
def _draw_contract_item(
    self,
    item: RenderItem,
    surface: Any,
    modulation: Color,
    context: RenderContext,
) -> None:
```

Keep the existing texture, text, nine-slice, primitive, opacity, and modulation
branches in that method. Public `draw_text()` and `draw_nine_slice()` continue
using `self.surface`; the callback passes the pipeline target to internal
surface-aware helpers. Do not create a second implementation in the pipeline.

- [x] **Step 5: Route effect frames through the planner**

In `render()`, preserve the existing early return and ordinary path when
`frame.submissions` is empty. When submissions exist, clear the screen pipeline,
clear the target once, build `RenderPlanBuilder.from_frame(frame, context)`,
execute it with `draw_item=lambda item, target: self._draw_contract_item(item, target, frame.modulation, context)`,
then preserve the existing legacy payload handling. Clear screen captures from
`start()`, `stop()`, `resize()`, and `set_surface()` as well.

- [x] **Step 6: Integrate runtime lifecycle and run green**

Keep `PygameRuntime` display ownership unchanged. Its existing calls to
`renderer.start`, `set_surface`, `resize`, and `stop` must now clear captures
through the renderer. Add tests for resize and restart cleanup, then run:

```bash
PYTHONPATH=src pytest -q tests/test_pygame_renderer.py tests/test_pygame_runtime.py
```

Expected: ordinary rendering, CanvasModulate-once behavior, legacy HUD, runtime
resize, and new ordered screen-effect tests all pass.

### Task 7: Wire Runner, Public Exports, Editor Status, and Export Coverage

**Files:**
- Modify: `src/expra_engine/runtime/project_runner.py`
- Modify: `src/expra_engine/runtime/__init__.py`
- Modify: `src/expra_engine/ui/viewport.py`
- Modify: `tests/test_editor_render_targets.py`
- Modify: `tests/test_export_exporter.py`
- Modify: `tests/test_export_manifest.py`

- [x] **Step 1: Add failing runner and editor tests**

Assert the normal project frame factory passes `extracted.submissions` into the
neutral `RenderFrame`, while the legacy Pygame payload remains present. Assert
that `build_editor_render_target()` returns ordinary visible items and a clear
unsupported-effect list for a scene containing screen components.

```python
def test_editor_target_reports_screen_effects_without_fake_pixels():
    scene = Scene("effects")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent("rectangle"))
    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(ScreenTextureComponent())
    target = build_editor_render_target(scene, viewport=(200, 100))
    assert [item.key for item in target.items] == ["background"]
    assert target.unsupported_effects == ("capture", "consumer")
```

Run the focused editor/runner tests. Expected failure is the absent
`unsupported_effects` field and missing runner propagation.

- [x] **Step 2: Carry submissions through the normal runner**

Extend the `RenderFrame` construction in `project_runner.frame_factory()`:

```python
return RenderFrame(
    extracted.items,
    elapsed=dt,
    payload=PygameRenderFrame(
        active_scene=current_engine.active_scene,
        interpolator=current_engine.transform_interpolator,
        interpolation_fraction=current_engine.interpolation_fraction,
        modulation=extracted.modulation,
    ),
    submissions=extracted.submissions,
)
```

Keep the empty-scene branch valid with the default empty submissions tuple.
Export `BackBufferCopyComponent`, `BackBufferCopyMode`,
`ScreenTextureComponent`, `ScreenTextureFilter`, `RenderEffect`,
`RenderPlan`, `RenderPlanBuilder`, and `PygameScreenPipeline` through the
runtime package's existing `__all__` pattern.

- [x] **Step 3: Expose explicit unsupported editor behavior**

Add `unsupported_effects: tuple[str, ...] = ()` to `EditorRenderTarget`. In
`build_editor_render_target()`, collect effect request entity IDs from
`frame.submissions` while retaining the existing `frame.visible_items(context)`
Tk preview path. Do not instantiate Pygame, copy surfaces, or alter scene
serialization in the editor.

- [x] **Step 4: Prove export inclusion without a new scanner**

Add an export smoke assertion around `_stage_pygame_runtime()` that checks the
staged runtime contains exactly these modules:

```python
for name in ("screen_texture.py", "render_pipeline.py", "pygame_screen_pipeline.py"):
    assert (staged_runtime / "runtime" / name).is_file()
```

Do not modify `DependencyGraph` or add Python import scanning. The existing
runtime-tree copy is the canonical export owner.

- [x] **Step 5: Run runner/editor/export tests to green**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_pygame_runtime.py tests/test_editor_render_targets.py tests/test_export_manifest.py tests/test_export_exporter.py
```

Expected: normal runner propagation, ordinary editor preview, explicit
unsupported status, and runtime export staging all pass.

### Task 8: Add End-to-End and Compatibility Coverage

**Files:**
- Modify: `tests/test_render_pipeline.py`
- Modify: `tests/test_pygame_screen_pipeline.py`
- Modify: `tests/test_pygame_renderer.py`
- Modify: `tests/test_render_extractor.py`
- Create: `tests/test_screen_texture_end_to_end.py`

- [x] **Step 1: Write the real Scene-to-Pygame integration test**

Create one scene containing, in order, a background primitive, a viewport
`BackBufferCopyComponent`, a later primitive, and a `ScreenTextureComponent`.
Extract the frame, build a plan, execute it through a real `PygameRenderer`
with injected fake surfaces, and record backend events. Assert:

```python
assert event_names == [
    "clear",
    "draw:background",
    "capture:screen",
    "draw:later",
    "blit:screen_texture",
]
```

Use a second explicit capture and consumer to prove that later draws do not
mutate the first snapshot and that recapture replaces it. Use two named slots
to prove automatic captures are independent.

- [x] **Step 2: Add modulation and ordinary-compatibility assertions**

Run the same ordinary scene through both the old direct renderer path and the
new extraction path with no effects. Assert identical draw ordering and colors.
For an effect scene, assert preceding pixels include CanvasModulate exactly once
and sampled ScreenTexture pixels receive only their own tint and opacity.

- [x] **Step 3: Run the integrated regression group**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_screen_texture_end_to_end.py \
  tests/test_render_extractor.py \
  tests/test_runtime_rendering.py \
  tests/test_pygame_renderer.py \
  tests/test_canvas_effects.py \
  tests/test_animated_sprite_2d.py \
  tests/test_animated_sprite_integration.py \
  tests/test_transform_interpolation.py \
  tests/test_transform_interpolation_runtime.py \
  tests/test_editor_render_targets.py \
  tests/test_export_manifest.py \
  tests/test_export_exporter.py
```

Expected: no ordinary visual, animation, interpolation, editor, legacy, or
export regression is introduced.

### Task 9: Full Verification and Adversarial Review

**Files:**
- Modify: no production files in this task; validation only.
- Create if required by BugGuard: `docs/bug_hunts/patch_reviews/PATCH-20260922-003-review.md`

- [x] **Step 1: Run the required focused suites in order**

Run each command with `PYTHONPATH=src` and record its complete exit status:

```bash
pytest -q tests/test_screen_texture.py
pytest -q tests/test_render_pipeline.py
pytest -q tests/test_pygame_screen_pipeline.py
pytest -q tests/test_component_schema.py tests/test_scene.py tests/test_entity.py
pytest -q tests/test_render_extractor.py tests/test_runtime_rendering.py
pytest -q tests/test_pygame_renderer.py tests/test_pygame_runtime.py
pytest -q tests/test_canvas_effects.py tests/test_animated_sprite_2d.py tests/test_animated_sprite_integration.py
pytest -q tests/test_transform_interpolation.py tests/test_transform_interpolation_runtime.py
pytest -q tests/test_editor_render_targets.py tests/test_export_manifest.py tests/test_export_exporter.py
```

The expected result for every command is exit code 0 with zero failures.

- [x] **Step 2: Run the complete repository suite**

Run:

```bash
PYTHONPATH=src pytest -q
```

Read the complete output and report the exact passed, failed, skipped, and
warning counts. A package-resolution mismatch must be reported rather than
treated as a pass.

- [x] **Step 3: Run static and repository checks**

Run:

```bash
PYTHONPATH=src python3 -m compileall -q src tests
ruff format --check src tests
ruff check src tests
pyright
mypy src
git diff --check
wc -l src/expra_engine/runtime/screen_texture.py src/expra_engine/runtime/render_pipeline.py src/expra_engine/runtime/pygame_screen_pipeline.py src/expra_engine/runtime/pygame_renderer.py
git status --short --untracked-files=all
```

If a configured tool is unavailable, record it as not run with the command and
reason. Do not claim a missing tool passed.

- [ ] **Step 4: Complete full A4 patch review**

Because this patch crosses serialization, render planning, backend pixels,
runtime lifecycle, and export boundaries, create
`PATCH-20260922-003-review.md` using the BugGuard template. The main auditor
provides the patch summary, exact diff, original task evidence, and test output.
Four independent validators write their own sections directly to the artifact;
Agent 5 reads those sections and writes its evidence audit before the main
auditor writes the rebuttal and final decision. Do not simulate missing
reviewers or backfill their sections.

- [x] **Step 5: Perform the final requirement checklist**

Confirm from source and tests that BackBufferCopy has a real ScreenTexture
consumer; no second renderer or shader compiler exists; no backend object enters
serialization; ordinary frames preserve their prior path; explicit capture,
automatic capture, frozen snapshots, mipmaps, lifecycle clearing, capabilities,
editor limitation, legacy behavior, export staging, and CanvasGroup deferral
are all documented as implemented, reused, adapted, deferred, or not
applicable.

- [x] **Step 6: Stop without committing**

Leave all code, tests, spec, and plan changes in the working tree. Do not run
`git commit`, `git push`, `git reset`, or destructive checkout commands.
