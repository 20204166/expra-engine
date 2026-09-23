"""Backend tests for Pygame screen capture, mipmaps, and sampling."""

import math
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from expra_engine.runtime.pygame_screen_pipeline import (
    PygameScreenPipeline,
    PygameScreenSnapshot,
    ScreenPipelineError,
    UnsupportedScreenPipelineFeature,
)
from expra_engine.runtime.render_pipeline import (
    DrawScreenTextureOp,
    RenderOrder,
    RenderPlan,
    RenderPlanBuilder,
)
from expra_engine.runtime.rendering import (
    Color,
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderItem,
    RenderPhase,
    Transform,
    Viewport,
)
from expra_engine.runtime.screen_texture import (
    BackBufferCopyMode,
    BackBufferCopyRequest,
    ScreenTextureDrawRequest,
    ScreenTextureFilter,
)
from expra_engine.ui_model.geometry import Rect


@dataclass
class _Rect:
    x: int
    y: int
    width: int
    height: int


class _Surface:
    def __init__(self, size=(100, 100), *, name="surface", content=None):
        self._size = size
        self.name = name
        self.content = name if content is None else content
        self.copies = 0
        self.subsurfaces = []
        self.blits = []
        self.fills = []

    def get_size(self):
        return self._size

    def copy(self):
        self.copies += 1
        return _Surface(self._size, name=f"{self.name}.copy", content=self.content)

    def subsurface(self, rect):
        self.subsurfaces.append(tuple(rect))
        return _Surface(
            (rect[2], rect[3]),
            name=f"{self.name}.sub",
            content=self.content,
        )

    def blit(self, source, destination):
        self.blits.append((source, destination))

    def fill(self, value, special_flags=None):
        self.fills.append((value, special_flags))

    def get_rect(self, **kwargs):
        center = kwargs.get("center", (0, 0))
        return _Rect(
            center[0] - self._size[0] // 2,
            center[1] - self._size[1] // 2,
            self._size[0],
            self._size[1],
        )


class _TransformAPI:
    def __init__(self):
        self.scales = []
        self.smoothscales = []
        self.rotations = []

    def scale(self, surface, size):
        self.scales.append((surface, size))
        return _Surface(size, name="scaled", content=surface.content)

    def smoothscale(self, surface, size):
        self.smoothscales.append((surface, size))
        return _Surface(size, name="smooth", content=surface.content)

    def rotate(self, surface, angle):
        self.rotations.append((surface, angle))
        return surface


class _Pygame:
    BLEND_RGBA_MULT = 7

    def __init__(self):
        self.transform = _TransformAPI()


class _FlaggedSurface(_Surface):
    def __init__(self, size=(100, 100), *, flags=0, name="surface", content=None):
        super().__init__(size, name=name, content=content)
        self.flags = flags

    def get_flags(self):
        return self.flags

    def copy(self):
        self.copies += 1
        return _FlaggedSurface(
            self._size,
            flags=self.flags,
            name=f"{self.name}.copy",
            content=self.content,
        )


class _AlphaPygame(_Pygame):
    SRCALPHA = 65536

    def __init__(self):
        super().__init__()
        self.transform = _AlphaTransformAPI()

    def Surface(self, size, flags=0):
        return _FlaggedSurface(size, flags=flags)


class _AlphaTransformAPI(_TransformAPI):
    def scale(self, surface, size):
        self.scales.append((surface, size))
        return _FlaggedSurface(
            size,
            flags=surface.get_flags(),
            name="scaled",
            content=surface.content,
        )

    def smoothscale(self, surface, size):
        self.smoothscales.append((surface, size))
        return _FlaggedSurface(
            size,
            flags=surface.get_flags(),
            name="smooth",
            content=surface.content,
        )


def context():
    return RenderContext(
        Viewport(0, 0, 100, 100),
        OrthographicCamera(width=10.0, height=10.0),
    )


def test_execute_interleaves_draw_capture_and_screen_draw():
    pygame = _Pygame()
    pipeline = PygameScreenPipeline(pygame)
    surface = _Surface()
    builder = RenderPlanBuilder()
    item = RenderItem("background", PrimitiveDescriptor("point"), Transform())
    builder.add_item(item, insertion_index=0)
    builder.add_capture(
        BackBufferCopyRequest(
            "capture",
            "screen",
            BackBufferCopyMode.VIEWPORT,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest("mirror", "screen", Transform(), 2.0, 2.0),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=2,
    )
    drawn = []

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=context(),
        draw_item=lambda render_item, target: drawn.append((render_item.key, target)),
    )

    assert [key for key, _ in drawn] == ["background"]
    assert surface.subsurfaces == [(0, 0, 100, 100)]
    assert len(surface.blits) == 1
    assert pipeline.snapshot("screen") is not None


def test_capture_stores_a_copy_and_does_not_alias_source():
    source = _Surface((8, 4), content="before")
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
        context=RenderContext(
            Viewport(0, 0, 8, 4),
            OrthographicCamera(width=8.0, height=4.0),
        ),
        draw_item=lambda item, target: None,
    )

    snapshot = pipeline.snapshot("screen")
    assert snapshot is not None
    assert snapshot.base is not source
    source.content = "after"
    assert snapshot.base.content == "before"


def test_tinted_sampling_does_not_mutate_source_or_snapshot():
    pygame = _Pygame()
    source = _Surface((100, 100), content="original")
    pipeline = PygameScreenPipeline(pygame)
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "consumer",
            "screen",
            Transform(),
            2.0,
            2.0,
            tint=Color(0.5, 0.25, 0.75, 0.8),
            opacity=0.5,
            filter=ScreenTextureFilter.NEAREST,
        ),
        phase=RenderPhase.TRANSPARENT,
        layer=0,
        insertion_index=1,
    )

    pipeline.execute(
        builder.build(),
        surface=source,
        context=context(),
        draw_item=lambda item, target: None,
    )

    snapshot = pipeline.snapshot("screen")
    assert snapshot is not None
    assert source.fills == []
    assert snapshot.base.fills == []
    assert pygame.transform.scales[-1][0].fills == [((128, 64, 191, 102), 7)]


def test_tint_and_opacity_use_an_alpha_surface_for_opaque_targets():
    pygame = _AlphaPygame()
    pipeline = PygameScreenPipeline(pygame)
    source = _FlaggedSurface(flags=0)

    result = pipeline._apply_tint_and_opacity(source, Color(0.5, 0.5, 0.5), 0.5)

    assert result.get_flags() & pygame.SRCALPHA
    assert result.fills == [((128, 128, 128, 128), pygame.BLEND_RGBA_MULT)]
    assert source.fills == []


def test_rotation_converts_opaque_scaled_pixels_to_alpha_surface():
    pygame = _AlphaPygame()
    pipeline = PygameScreenPipeline(pygame)
    source = _FlaggedSurface(flags=0)
    pipeline._captures["screen"] = PygameScreenSnapshot((0, 0), (source,))

    request = ScreenTextureDrawRequest(
        "effect",
        "screen",
        Transform(rotation=30.0),
        2.0,
        2.0,
        filter=ScreenTextureFilter.NEAREST,
    )
    operation = DrawScreenTextureOp(RenderOrder(0, 0, 0.0, 0), request)
    pipeline.execute(
        RenderPlan((operation,)),
        surface=_FlaggedSurface(flags=pygame.SRCALPHA),
        context=context(),
        draw_item=lambda item, target: None,
    )

    assert pygame.transform.rotations[-1][0].get_flags() & pygame.SRCALPHA


def test_missing_backend_operation_is_explicit():
    pygame = SimpleNamespace(transform=SimpleNamespace())
    pipeline = PygameScreenPipeline(pygame)
    with pytest.raises(UnsupportedScreenPipelineFeature):
        pipeline._scale(_Surface((2, 2)), (4, 4), linear=False)


def test_missing_crop_operation_is_explicit():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = SimpleNamespace(get_size=lambda: (8, 4))
    with pytest.raises(UnsupportedScreenPipelineFeature):
        pipeline._crop_uv(surface, Rect(0.25, 0.0, 0.5, 1.0))


def test_missing_capture_operation_is_explicit():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = SimpleNamespace(get_size=lambda: (8, 4))
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    with pytest.raises(UnsupportedScreenPipelineFeature):
        pipeline.execute(
            builder.build(),
            surface=surface,
            context=RenderContext(
                Viewport(0, 0, 8, 4),
                OrthographicCamera(width=8.0, height=4.0),
            ),
            draw_item=lambda item, target: None,
        )


def test_missing_copy_for_tint_is_explicit_and_non_mutating():
    class _FillOnlySurface:
        def __init__(self):
            self.fills = []

        def fill(self, value, special_flags=None):
            self.fills.append((value, special_flags))

    source = _FillOnlySurface()
    pipeline = PygameScreenPipeline(_Pygame())
    with pytest.raises(UnsupportedScreenPipelineFeature):
        pipeline._apply_tint_and_opacity(source, Color(0.5, 0.5, 0.5), 0.5)
    assert source.fills == []


def test_rect_capture_projects_local_world_rect_and_clips():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = _Surface()
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest(
            "capture",
            "screen",
            BackBufferCopyMode.RECT,
            Transform(position=(0.0, 0.0, 0.0)),
            rect=Rect(-2.5, -2.5, 5.0, 5.0),
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=context(),
        draw_item=lambda item, target: None,
    )

    assert surface.subsurfaces == [(25, 25, 50, 50)]


def test_rect_capture_rounds_projected_edges_outward():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = _Surface()
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest(
            "capture",
            "screen",
            BackBufferCopyMode.RECT,
            Transform(),
            rect=Rect(-2.45, -2.45, 4.9, 4.9),
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=context(),
        draw_item=lambda item, target: None,
    )

    assert surface.subsurfaces == [(25, 25, 50, 50)]


def test_viewport_capture_outside_surface_is_not_stored():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = _Surface()
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest(
            "capture",
            "screen",
            BackBufferCopyMode.RECT,
            Transform(position=(20.0, 20.0, 0.0)),
            rect=Rect(0.0, 0.0, 1.0, 1.0),
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=context(),
        draw_item=lambda item, target: None,
    )

    assert surface.subsurfaces == []
    assert pipeline.snapshot("screen") is None


def test_viewport_capture_preserves_nonzero_viewport_origin():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = _Surface((200, 150))
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    capture_context = RenderContext(
        Viewport(10, 20, 80, 60),
        OrthographicCamera(width=8.0, height=6.0),
    )

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=capture_context,
        draw_item=lambda item, target: None,
    )

    assert surface.subsurfaces == [(10, 20, 80, 60)]
    assert pipeline.snapshot("screen").origin == (10, 20)


def test_mipmap_generation_builds_down_to_one_pixel():
    pygame = _Pygame()
    pipeline = PygameScreenPipeline(pygame)
    surface = _Surface((8, 4))
    builder = RenderPlanBuilder()
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "effect",
            "screen",
            Transform(),
            2.0,
            2.0,
            filter=ScreenTextureFilter.LINEAR_MIPMAP,
            lod=2,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=RenderContext(
            Viewport(0, 0, 8, 4),
            OrthographicCamera(width=8.0, height=4.0),
        ),
        draw_item=lambda item, target: None,
    )

    snapshot = pipeline.snapshot("screen")
    assert snapshot is not None
    assert [level.get_size() for level in snapshot.levels] == [
        (8, 4),
        (4, 2),
        (2, 1),
        (1, 1),
    ]


def test_mipmap_lod_is_clamped_to_the_last_available_level():
    pygame = _Pygame()
    pipeline = PygameScreenPipeline(pygame)
    source = _Surface((8, 4))
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "effect",
            "screen",
            Transform(),
            2.0,
            2.0,
            filter=ScreenTextureFilter.LINEAR_MIPMAP,
            lod=999.0,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )

    pipeline.execute(
        builder.build(),
        surface=source,
        context=RenderContext(
            Viewport(0, 0, 8, 4),
            OrthographicCamera(width=8.0, height=4.0),
        ),
        draw_item=lambda item, target: None,
    )

    assert pygame.transform.smoothscales[-1][0].get_size() == (1, 1)


def test_one_pixel_mipmap_pyramid_is_a_valid_sampling_source():
    pygame = _Pygame()
    pipeline = PygameScreenPipeline(pygame)
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "effect",
            "screen",
            Transform(),
            1.0,
            1.0,
            filter=ScreenTextureFilter.NEAREST_MIPMAP,
            lod=999.0,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )

    pipeline.execute(
        builder.build(),
        surface=_Surface((1, 1)),
        context=RenderContext(
            Viewport(0, 0, 1, 1),
            OrthographicCamera(width=1.0, height=1.0),
        ),
        draw_item=lambda item, target: None,
    )

    snapshot = pipeline.snapshot("screen")
    assert snapshot is not None
    assert [level.get_size() for level in snapshot.levels] == [(1, 1)]
    assert pygame.transform.scales[-1][0].get_size() == (1, 1)


def test_uv_crop_uses_normalized_pixel_bounds():
    pygame = _Pygame()
    pipeline = PygameScreenPipeline(pygame)
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "effect",
            "screen",
            Transform(),
            2.0,
            2.0,
            uv_rect=Rect(0.25, 0.25, 0.5, 0.5),
            filter=ScreenTextureFilter.NEAREST,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )

    pipeline.execute(
        builder.build(),
        surface=_Surface((8, 4)),
        context=RenderContext(
            Viewport(0, 0, 8, 4),
            OrthographicCamera(width=8.0, height=4.0),
        ),
        draw_item=lambda item, target: None,
    )

    snapshot = pipeline.snapshot("screen")
    assert snapshot is not None
    assert snapshot.base.subsurfaces == [(2, 1, 4, 2)]
    assert pygame.transform.scales[-1][0].get_size() == (4, 2)


def test_nearest_and_linear_filters_select_matching_scale_operations():
    pygame = _Pygame()
    pipeline = PygameScreenPipeline(pygame)
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    for index, filter_mode in enumerate(
        (ScreenTextureFilter.NEAREST, ScreenTextureFilter.LINEAR),
        start=1,
    ):
        builder.add_screen_texture(
            ScreenTextureDrawRequest(
                f"effect-{index}",
                "screen",
                Transform(),
                2.0,
                2.0,
                filter=filter_mode,
            ),
            phase=RenderPhase.OPAQUE,
            layer=0,
            insertion_index=index,
        )

    pipeline.execute(
        builder.build(),
        surface=_Surface((100, 100)),
        context=context(),
        draw_item=lambda item, target: None,
    )

    assert [size for _, size in pygame.transform.scales] == [(20, 20)]
    assert [size for _, size in pygame.transform.smoothscales] == [(20, 20)]


def test_screen_texture_without_capture_is_an_explicit_error():
    request = ScreenTextureDrawRequest("effect", "screen", Transform(), 2.0, 2.0)
    operation = DrawScreenTextureOp(RenderOrder(0, 0, 0.0, 0), request)
    pipeline = PygameScreenPipeline(_Pygame())
    with pytest.raises(ScreenPipelineError, match="has not been captured"):
        pipeline.execute(
            RenderPlan((operation,)),
            surface=_Surface(),
            context=context(),
            draw_item=lambda item, target: None,
        )


def test_screen_texture_rotation_subtracts_camera_rotation():
    pygame = _Pygame()
    pipeline = PygameScreenPipeline(pygame)
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "effect",
            "screen",
            Transform(rotation=45.0),
            2.0,
            2.0,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    render_context = context()
    render_context.camera.rotation = math.radians(15.0)

    pipeline.execute(
        builder.build(),
        surface=_Surface(),
        context=render_context,
        draw_item=lambda item, target: None,
    )

    assert pygame.transform.rotations[-1][1] == pytest.approx(30.0)


def test_named_capture_is_replaced_by_later_capture():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = _Surface()
    builder = RenderPlanBuilder()
    for index in (0, 1):
        builder.add_capture(
            BackBufferCopyRequest(
                f"capture-{index}",
                "screen",
                BackBufferCopyMode.VIEWPORT,
            ),
            phase=RenderPhase.OPAQUE,
            layer=0,
            insertion_index=index,
        )

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=context(),
        draw_item=lambda item, target: None,
    )
    assert surface.subsurfaces == [(0, 0, 100, 100), (0, 0, 100, 100)]
    assert pipeline.snapshot("screen") is not None


def test_named_capture_replacement_replaces_the_snapshot_and_content():
    pipeline = PygameScreenPipeline(_Pygame())
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    plan = builder.build()

    pipeline.execute(
        plan,
        surface=_Surface(content="first"),
        context=context(),
        draw_item=lambda item, target: None,
    )
    first = pipeline.snapshot("screen")

    pipeline.execute(
        plan,
        surface=_Surface(content="second"),
        context=context(),
        draw_item=lambda item, target: None,
    )
    second = pipeline.snapshot("screen")

    assert first is not None
    assert second is not None
    assert second is not first
    assert first.base.content == "first"
    assert second.base.content == "second"


def test_clear_drops_runtime_owned_surfaces_between_scenes():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = _Surface()
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("capture", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    pipeline.execute(
        builder.build(),
        surface=surface,
        context=context(),
        draw_item=lambda item, target: None,
    )
    assert pipeline.capture_ids == ("screen",)
    pipeline.clear()
    assert pipeline.capture_ids == ()


def test_clear_removes_every_named_capture_slot():
    pipeline = PygameScreenPipeline(_Pygame())
    surface = _Surface()
    builder = RenderPlanBuilder()
    for index, capture_id in enumerate(("left", "right")):
        builder.add_capture(
            BackBufferCopyRequest(
                f"capture-{index}",
                capture_id,
                BackBufferCopyMode.VIEWPORT,
            ),
            phase=RenderPhase.OPAQUE,
            layer=0,
            insertion_index=index,
        )

    pipeline.execute(
        builder.build(),
        surface=surface,
        context=context(),
        draw_item=lambda item, target: None,
    )
    assert set(pipeline.capture_ids) == {"left", "right"}
    pipeline.clear()
    assert pipeline.capture_ids == ()
    assert pipeline.snapshot("left") is None
    assert pipeline.snapshot("right") is None


def test_missing_mipmap_capture_is_an_explicit_error():
    pipeline = PygameScreenPipeline(_Pygame())
    with pytest.raises(ScreenPipelineError):
        pipeline._generate_mipmaps("missing")
