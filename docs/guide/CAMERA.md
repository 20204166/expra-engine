# Camera

## Camera2D

`Camera2D` (`core/scene/camera.py`) is the 2D orthographic camera. Game space is
y-up; screen space is y-down.

```python
from expra_engine.core.scene.camera import Camera2D

camera = Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))
```

Key fields and defaults: `position=(0,0)`, `target_position=(0,0)`,
`zoom=1.0`, `offset=(0,0)`, `rotation=0.0`, `position_smoothing_enabled=False`,
`position_smoothing_speed=5.0`, `rotation_smoothing_enabled=False`,
`rotation_smoothing_speed=5.0`, drag margins (default `0.2`),
`limit_enabled=False` with default limits `±1e7`.

`pixel_ratio = viewport_pixels / game_units`; `width`/`height` derive from
viewport and ratio.

## Coordinate transforms

```python
camera.translate_to_screen(point)   # world -> screen (pixels)
camera.translate_to_game(point)     # screen -> world
camera.project(point, viewport)     # arbitrary viewport
camera.unproject(point, viewport)
```

Both respect `zoom`, `offset`, and `rotation`. Without rotation:

```
screen_x = (x - left) * pixel_ratio
screen_y = (top - y) * pixel_ratio
```

## Smoothing and limits

- `position_smoothing_enabled` + `position_smoothing_speed` ease toward
  `target_position`.
- `set_limits(l, r, t, b)` / `clear_limits()` clamp the camera within bounds.
- Drag margins allow horizontal/vertical look-ahead toward a target.

## SceneCamera

`SceneCamera` (`core/scene/camera.py`) is a JSON-compatible dict stored on a
`Scene` that carries camera config (`target_entity_id`, and any `Camera2D`
fields) and applies via `apply_to(camera)`.

## Gameplay vs editor camera

- **Runtime** uses the scene's configured camera (`scene.camera`).
- **Editor** uses a pannable/zoomable `ViewportCamera`; the scene camera's frame
  is drawn as an overlay. In Play mode the editor viewport switches to the
  scene camera.

## Camera ≠ streaming anchor

The camera is not the World streaming anchor. `StreamingAnchorComponent` drives
Level residency; camera context (`WorldCameraContextMixin`) only determines
which Level the camera is inside for continuity. See
[World Streaming](WORLD_STREAMING.md).
