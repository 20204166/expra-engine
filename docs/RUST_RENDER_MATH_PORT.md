# Expra Render-Math PyO3 Port

**Status:** Visibility and marker-projection kernels build and pass parity checks in the Linux CPython 3.12 native wheel; end-to-end marker-performance comparison remains pending
**Python reference:** Expra 0.6.2.1, repository HEAD `4744b0138545e11ef629c64693e8692b2729a308` plus the pending release changes
**Reference integration pattern:** User-owned `/home/btn17/Downloads/railrefund-main` PyO3 crates; no RailRefund application/render math is reused.

## Scope

Port only Expra's measured **batch visibility/projection math** behind one
Python-to-Rust adapter. Do not rewrite `PygameRenderer`, `RenderItem`, camera
ownership, materials, lighting, texture loading, editor widgets, World
streaming, or render-plan execution in Rust. Python remains the owner of those
contracts and supplies already-composed item/camera data to the native kernel.

The Rust implementation first mirrors the current Python behavior. It is not
optimized until parity tests prove the copy is exact and an end-to-end benchmark
shows that Python packing plus the PyO3 boundary still wins.

## Measured audit findings

Expra's live Editor Play observability on Blacksite Relay (66 authored entities,
1280×800 viewport) most recently measured:

| Stage | p50 | p95 |
|---|---:|---:|
| `render:backend` | 7.48 ms | 9.23 ms |
| `render:extract` | 2.39 ms | 3.30 ms |
| `render:plan` | 0.42 ms | 0.67 ms |

A local Pygame profile found Python `visible_items` / `RenderItem.is_visible` /
`_projected_bounds` as the main measured Python math cluster. Camera projection
and item bounds are the candidate native kernel. The Editor pixel bridge also
used to run visibility culling twice (texture preflight and draw); the preflight
result is now reused for drawing, with a regression asserting one visibility
evaluation per item.

Deep mounted HUD extraction had a separate quadratic cost: for a 50-deep
hierarchy its p50 was 27.19 ms before the top-down local-pose pass and
World-pose skip. It is now 1.91 ms. That hot path was fixed in Python because a
linear traversal is simpler than a native port for work the algorithm need not
repeat.

The final Blacksite render-stress probe at 1280×800 measured 2.416 s for 200
frames (12.08 ms/frame), versus 3.252 s (16.26 ms/frame) before the measured
Python fixes. The probe reported bounded resource caches and no repeated render
diagnostics.

## Canonical ownership and single bridge

- `RenderItem` and `RenderFrame` in `src/expra_engine/runtime/rendering.py`
  remain Expra's public, renderer-neutral contracts.
- `RenderFrame.visible_items(context)` is the canonical query used by runtime,
  editor, preflight, and render-plan consumers.
- `src/expra_engine/runtime/render_math.py` is the **only Python module that
  imports/calls the optional PyO3 extension**. It packs inputs, validates native
  results, and owns the Python fallbacks for both `RenderItem.is_visible()` and
  `Camera2D.translate_to_screen()`.
- Runtime and Editor consume the returned visible items; editor marker drawing
  consumes batched projected points. There must not be per-renderer PyO3 wrappers,
  per-item FFI calls, or a second renderer.

## Faithful input and output contract

One native call receives one ordered batch of item records plus one camera and
viewport record. Python composes hierarchy/sprite transforms and serializes
these values; Rust does not inspect Python Entities, materials, assets, scripts,
or scene documents.

Each item record contains:

1. coordinate space (`world` or `viewport`), primitive kind, and visibility;
2. resolved visual position `(x,y,z)`, rotation in degrees, and 2D scale;
3. primitive size, optional radius, line thickness, outline width, and local
   points for polygon/line primitives;
4. optional normalized viewport anchor and pixel offset for mounted HUD items.

The camera record contains actual position, offset, width, height, rotation,
near, and far values. The viewport record contains integer `(x,y,width,height)`.
The native result is one Boolean visibility value per input item, in input
order. It does not sort, mutate, allocate renderer objects, or return drawing
commands.

The editor-marker operation is separate and accepts one flat ordered `x/y`
point buffer plus the Python camera's `left`, `top`, `pixel_ratio`, view center,
rotation, and viewport width/height. It returns a flat ordered list of projected
screen-coordinate pairs. It mirrors `Camera2D.translate_to_screen`'s
zero-rotation operation order and rotated y-down screen convention. It does not
select entities, inspect transforms, choose marker styles, or call Canvas.
`native_projection_available()` detects this optional operation independently
from visibility-kernel availability, so a stale or malformed projection symbol
does not disable visibility math. Runtime projection failures disable only that
operation and use the Camera2D reference path.

The Rust baseline must mirror the Python rules exactly:

- camera projection: unrotated and rotated formulas, offset, dimensions, and
  viewport origin;
- batched editor-marker projection: exact `Camera2D.translate_to_screen`
  coordinate convention and input ordering;
- viewport-space anchors: y-up `x/y` offsets, local rotation/scale, and fixed
  pixel placement independent of camera pose;
- visible depth range: inclusive `near <= z <= far`;
- bounds for point, circle, rectangle/rect, rounded rectangle, polygon, line,
  unsupported-as-rectangle fallback, outlines, and line thickness;
- inclusive viewport intersection at all four edges.

Malformed packed-array lengths, invalid enum codes, and non-finite inputs return
a native error. The Python adapter catches native availability/contract errors,
disables the extension for that process with one bounded diagnostic, and uses
the Python reference mask rather than risking missing or incorrect pixels.

## PyO3 packaging and engine wheels

RailRefund's local implementation uses separate `native/<crate>` directories
with `Cargo.toml`, a Maturin-backed `pyproject.toml`, a `cdylib`, optional Python
imports, and parity tests. Expra will use that **integration pattern only**:

- `native/expra_render_math/Cargo.toml`
- `native/expra_render_math/pyproject.toml`
- `native/expra_render_math/src/lib.rs`

The main Expra setuptools build remains Python-only by default. Its conditional
`setuptools-rust` hook builds the same PyO3 kernel into platform-tagged
`expra-engine` wheels when `EXPRA_BUILD_RUST=1`; `EXPRA_BUILD_RUST=0` emits the
universal fallback wheel. The normal build script defaults to `auto`: it emits
both when Cargo is available, and only the universal wheel otherwise. Rust
source/build inputs are hashed into a packaged manifest so changes trigger the
existing version-diff logic; compiled extension bytes do not cause repeated
version bumps across OS builds.

Tagged releases build native wheels for Linux, macOS, and Windows, plus one
`py3-none-any` fallback. Both online installers download/hash-check the latest
same-version set and ask pip to select the compatible platform wheel. CPython
3.12+ can use the abi3 native extension; other compatible Python/platform
combinations retain the Python fallback. The Maturin crate remains useful for
local development and standalone kernel testing, but the released extension is
bundled into the engine wheel.

## Test and optimization gates

1. Run the Python reference against deterministic cases for world/viewport
   coordinates, all primitive bounds, edge-touching pixels, camera offset,
   zoom, rotation, and near/far depth.
2. When the extension is built, compare every native mask with the Python
   reference on those fixtures and seeded generated inputs. No tolerance is
   allowed for visibility booleans; underlying projected coordinates and bounds
   must match to a documented floating tolerance before optimizing. Batched
   marker projection is covered by the same extension build and has a separate
   Python/Rust coordinate parity matrix for unrotated/rotated cameras, offsets,
   positive/negative points, exact viewport corners, malformed buffers, and
   overflow rejection.
3. Run Editor Pygame pixel tests and standalone World render tests through the
   single adapter; verify the missing-extension and native-error fallback paths.
4. Benchmark extraction/culling, packing, native call, and end-to-end render
   separately at representative item counts (64, 256, 1024, and 4096), after
   warm-up and across repeated samples. Compare p50 and p95; keep native enabled
   only where the end-to-end call improves, not merely the Rust kernel.
5. Only after exact parity and measured end-to-end gain, optimize Rust data
    layout, early culling, or batch math. Re-run the complete parity matrix after
    each optimization.

### Observability-backed mode comparison

For source-tree development, build the extension in the active Expra environment
with Maturin, then run:

```bash
maturin develop --release --manifest-path native/expra_render_math/Cargo.toml
python tools/render_math_benchmark.py --mode all --entities 1024 --warmups 20 --iterations 100
```

The benchmark records bounded p50/p95 distributions and batch counters through
Expra's `ObservabilityWatcher`, and verifies output equality against the Python
reference before accepting samples. Its modes are:

- `python`: Python reference-only baseline;
- `hybrid`: normal production bridge, using Rust when available and falling back
  to Python if unavailable or broken;
- `rust-only`: strict Rust-kernel execution that raises on missing/failed native
  code, with no visibility-math fallback.

`rust-only` still uses Python-owned item ordering, input packing, and result
selection; those responsibilities are not duplicated in Rust. The benchmark
prewarms the immutable ordered-item tuple, then measures repeated visibility
selection, including per-call Python batch packing and PyO3 overhead. Sorting is
paid once per RenderFrame and excluded from the repeated samples. It does not
measure Pygame rasterization or full frame extraction. Set `--mode python`,
`hybrid`, or `rust-only` to run one path. A strict Rust measurement requires the
extension and fails rather than silently substituting Python. Output equality
against the Python reference is checked before accepting samples.

Current bundled-wheel observation on Python 3.12 / Linux x86_64 with 1,024
synthetic items, 20 warmups, and 100 samples: Python reference p50/p95
**41.44/48.13 ms**; hybrid p50/p95 **2.14/3.32 ms**; strict Rust p50/p95
**2.09/3.44 ms**. All 100 samples per mode matched. This measures only the
visibility-selection path and is evidence for that workload, not a whole-frame
or real-game speedup claim. The normal hybrid path is the release-relevant
comparison; strict mode adds no fallback guarantee and remains a diagnostic mode.

## Python viewport/runtime profiles

A reproducible real-Qt motion harness is checked in at
`tools/viewport_motion_benchmark.py`; `--marker-ratio` controls how many entities
are non-visual editor markers, and the harness reports event-wall distributions
and actual `render:extract`/`render:plan` observations. On this Python 3.12 /
PySide6 Linux workstation, the current 1,000-entity / 30-event pan run measured
p50/p95 **26.00/28.11 ms**, compared with the earlier pre-optimization
**170.76/185.19 ms**. The 10,000-entity / 20-event pan run measured
**165.01/212.76 ms** and an initial render of **2.25 s**, compared with the
earlier **264.78/335.93 ms** event-wall profile. Both post-change runs recorded
zero `render:extract` observations during camera motion. Reproduce with:

```bash
python tools/viewport_motion_benchmark.py --entities 1000 --events 30
python tools/viewport_motion_benchmark.py --entities 10000 --events 20 --marker-ratio 0.2
```

At 10k entities, pan still exceeds the 16.67 ms frame budget; the remaining
profile is dominated by marker projection/update and Python native-input packing.

For 5,000 Level entities / 7,500 components, a five-iteration observability
probe measured protobuf conversion p50/p95 **118.52/130.99 ms**, construction
**108.08/117.63 ms**, and total document load **222.53/247.35 ms**. A paired
conversion microbenchmark of the attempted component-dictionary allocation
reduction measured p50 **127.40 ms** before and **127.01 ms** after (20 runs);
the difference was within noise, so that codec change was reverted. A real
Blacksite Play snapshot measured `runtime:tick`
p50/p95 **2.39/3.54 ms** over 899 samples; the much larger
`editor:preview:tick` includes rendering and UI work. Neither document conversion
nor Engine tick received speculative changes.

## Current bridge consolidation

The Editor pixel path now computes `visible_items` once, passes that tuple to
texture preflight, then to `PygameRenderer.render_previsible()`. `RenderPlanBuilder`
filters its draw submissions against those same item identities when previsible
items are supplied. Other callers use `RenderFrame.visible_items()`. This keeps
the Python fallback, native kernel, and drawing consumers on one visibility
result per frame.
