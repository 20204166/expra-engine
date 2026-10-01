"""Real-Pygame renderer bootstrap for tests that assert on actual pixel output.

Builds and starts a ``PygameRenderer`` against a fresh ``Surface`` with the
``Viewport``/``OrthographicCamera``/``RenderContext`` ceremony every real-pixel
rendering test otherwise repeats. Tests that drive a *fake* pygame module
(testing call contracts, not real pixels) have different needs and do not use
this helper.
"""

from __future__ import annotations

from typing import Any

from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.rendering import OrthographicCamera, RenderContext, Viewport


def make_renderer(
    pygame_module: Any,
    size: tuple[int, int] = (101, 101),
    *,
    flags: int = 0,
    clear_color: tuple[int, ...] | None = (0, 0, 0),
    camera: OrthographicCamera | None = None,
    camera_width: float = 10.0,
    camera_height: float = 10.0,
    **renderer_kwargs: Any,
) -> tuple[PygameRenderer, Any]:
    """Return a started ``(renderer, surface)`` pair ready to render frames.

    Pass an existing ``camera`` to reuse its mutable state (position/zoom/
    rotation) across repeated draws; otherwise one is built from
    ``camera_width``/``camera_height``. Any other ``PygameRenderer`` keyword
    (``observer``, ``lighting_pass``, ``resource_provider``,
    ``normal_map_resolver``, ``pixel_art_mode``, ...) passes straight through.
    """
    surface = pygame_module.Surface(size, flags) if flags else pygame_module.Surface(size)
    renderer = PygameRenderer(
        pygame_module,
        surface,
        clear_color=clear_color,
        **renderer_kwargs,
    )
    renderer.start(
        RenderContext(
            Viewport(0, 0, size[0], size[1]),
            camera if camera is not None else OrthographicCamera(
                width=camera_width, height=camera_height
            ),
        )
    )
    return renderer, surface
