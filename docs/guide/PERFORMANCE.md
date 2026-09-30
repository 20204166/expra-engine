# Performance

This page documents the current performance architecture and the measured
limits known from the repository. Numbers are dated where available; re-measure
before relying on them.

## Architecture

- The render pipeline is **CPU** (Pygame); there is no GPU backend.
- `extract_render_frame` builds a `RenderFrame`; `RenderPlanBuilder` sorts into
  an ordered operation list; `PygameRenderer` draws.
- Resource reads go through `ResourceService` with a bounded cache.
- The editor preview reuses the same `PygameRenderer`, bridged into Tk via
  Pillow (benchmarked ~4–7× faster than the old PNG encode/decode path).
- World metadata load is lightweight (a World is a small frozen dataclass); a
  Level is materialized only when loaded/activated.

## Known cost centers

- Editor presentation: pixel-bridge conversion per frame, plus Tk canvas
  overlays.
- World streaming: Level materialization off the owner thread (bounded by
  `max_concurrent_loads`, default 2).
- Lighting: per-pixel 2D light composition; normal mapping adds a NumPy
  surfarray pass and requires `numpy`.

## Measured baselines

See the historical `docs/PERFORMANCE_BASELINE.md` and `PERFORMANCE_AUDIT.md`
(repo root) for earlier measurements. Those are snapshots at the time they were
taken; treat specific numbers as dated.

## Sprite scaling mode

`PygameRenderer` accepts a `pixel_art_mode: bool = False` constructor argument.

- `False` (default): uses `pygame.transform.smoothscale` — bilinear, suited to photography or large smooth artwork.
- `True`: uses `pygame.transform.scale` — nearest-neighbour, suited to pixel art. Eliminates blur when 32×32 sprites are scaled to 2× or more.

Pass it at launch-site creation, not per-frame. Example in a standalone launcher:

```python
renderer = PygameRenderer(
    pygame, None,
    screen_size=(1100, 700),
    pixel_art_mode=True,  # nearest-neighbour globally for all sprites
)
```

There is no per-sprite override; `pixel_art_mode` is a renderer-wide setting.

## Performance probes (MCP)

`performance_probe` distinguishes bounded retry/log flood from an actual
retained-resource leak with real before/after measurements (`render_stress`,
`resource_cache`, `document_load`, `editor_redraw_stress`), returning a verdict
of `bounded` / `growing` / `inconclusive` — it never asserts a leak without
retention evidence.
