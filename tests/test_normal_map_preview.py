from __future__ import annotations

import pygame

from expra_engine.runtime.rendering import NormalMapDescriptor
from expra_engine.ui.normal_map_preview import build_normal_map_preview


def test_normal_map_preview_builds_four_non_mutating_views() -> None:
    albedo = pygame.Surface((4, 4), pygame.SRCALPHA, 32)
    albedo.fill((180, 120, 60, 200))
    normal = pygame.Surface((4, 4), pygame.SRCALPHA, 32)
    normal.fill((255, 128, 128, 255))
    original = normal.copy()
    descriptor = NormalMapDescriptor(
        mode="explicit",
        texture_id="assets://stone_normal.png",
    )

    preview = build_normal_map_preview(pygame, albedo, normal, descriptor)

    assert tuple(preview.views) == ("Raw", "Decoded normal", "Lit", "Orientation test")
    assert all(surface.get_size() == (4, 4) for surface in preview.views.values())
    assert preview.render_lit(2.0, 2.0, 1.0).get_size() == (4, 4)
    assert pygame.image.tostring(normal, "RGBA") == pygame.image.tostring(original, "RGBA")
