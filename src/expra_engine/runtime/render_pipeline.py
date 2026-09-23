"""Ordered renderer-neutral 2D render planning.

Expra's existing ``RenderFrame.items`` is intentionally preserved as the
canonical draw-item contract. This module adds the missing *ordered operation*
layer required by effects that must happen between draw items, notably
BackBufferCopy and screen-texture consumers.

The planner borrows three mature ideas from Godot's canvas renderer:

1. capture requests participate in deterministic canvas ordering;
2. screen-texture capture is demand-driven and cached for later consumers;
3. mipmaps are generated lazily only when a consumer actually needs them.

It deliberately does not port RID ownership, GPU command lists, shader
compilation, render servers, framebuffers, or a second renderer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, TypeAlias

from expra_engine.runtime.rendering import (
    RenderContext,
    RenderFrame,
    RenderItem,
    RenderPhase,
    Transform,
)
from expra_engine.runtime.screen_texture import (
    BackBufferCopyMode,
    BackBufferCopyRequest,
    RenderEffect,
    ScreenTextureDrawRequest,
)

__all__ = (
    "CaptureScreenOp",
    "DrawItemOp",
    "DrawScreenTextureOp",
    "GenerateScreenMipmapsOp",
    "RenderOperation",
    "RenderOrder",
    "RenderPlan",
    "RenderPlanBuilder",
    "ScreenPipelineRequirements",
)


@dataclass(frozen=True, order=True)
class RenderOrder:
    """Stable total ordering shared by draw and non-draw canvas operations."""

    phase: int
    layer: int
    depth: float
    insertion_index: int

    def __post_init__(self) -> None:
        if self.phase not in tuple(phase.value for phase in RenderPhase):
            raise ValueError("phase is not a valid RenderPhase value")
        if not math.isfinite(float(self.depth)):
            raise ValueError("depth must be finite")
        if self.insertion_index < 0:
            raise ValueError("insertion_index must be non-negative")

    @classmethod
    def from_item(cls, item: RenderItem, insertion_index: int) -> "RenderOrder":
        if not isinstance(item, RenderItem):
            raise TypeError("item must be RenderItem")
        return cls(
            item.phase.value,
            item.layer,
            item.world_transform.position[2],
            insertion_index,
        )

    @classmethod
    def from_effect(
        cls,
        phase: RenderPhase,
        layer: int,
        transform: Transform,
        insertion_index: int,
    ) -> "RenderOrder":
        if not isinstance(phase, RenderPhase):
            raise TypeError("phase must be RenderPhase")
        if not isinstance(transform, Transform):
            raise TypeError("transform must be Transform")
        return cls(phase.value, int(layer), transform.position[2], insertion_index)


@dataclass(frozen=True)
class DrawItemOp:
    order: RenderOrder
    item: RenderItem


@dataclass(frozen=True)
class CaptureScreenOp:
    """Capture the framebuffer state produced by all earlier operations."""

    order: RenderOrder
    request: BackBufferCopyRequest
    automatic: bool = False


@dataclass(frozen=True)
class GenerateScreenMipmapsOp:
    """Generate/update a mip pyramid for the current named capture."""

    order: RenderOrder
    capture_id: str

    def __post_init__(self) -> None:
        if not self.capture_id:
            raise ValueError("capture_id must not be empty")


@dataclass(frozen=True)
class DrawScreenTextureOp:
    order: RenderOrder
    request: ScreenTextureDrawRequest


RenderOperation: TypeAlias = (
    DrawItemOp | CaptureScreenOp | GenerateScreenMipmapsOp | DrawScreenTextureOp
)


@dataclass(frozen=True)
class ScreenPipelineRequirements:
    screen_capture: bool = False
    screen_texture: bool = False
    screen_texture_mipmaps: bool = False

    def __post_init__(self) -> None:
        if self.screen_texture_mipmaps and not self.screen_texture:
            raise ValueError("screen_texture_mipmaps requires screen_texture")
        if self.screen_texture and not self.screen_capture:
            raise ValueError("screen_texture requires screen_capture")


@dataclass(frozen=True)
class RenderPlan:
    """Immutable ordered operation stream for one frame."""

    operations: tuple[RenderOperation, ...] = ()
    requirements: ScreenPipelineRequirements = field(
        default_factory=ScreenPipelineRequirements
    )

    def __post_init__(self) -> None:
        operations = tuple(self.operations)
        object.__setattr__(self, "operations", operations)
        previous: RenderOrder | None = None
        for operation in operations:
            if previous is not None and operation.order < previous:
                raise ValueError("render operations must already be ordered")
            previous = operation.order

    @property
    def draw_items(self) -> tuple[RenderItem, ...]:
        return tuple(
            operation.item
            for operation in self.operations
            if isinstance(operation, DrawItemOp)
        )

    @property
    def capture_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for operation in self.operations:
            if isinstance(operation, CaptureScreenOp):
                capture_id = operation.request.capture_id
                if capture_id not in seen:
                    seen.append(capture_id)
        return tuple(seen)


@dataclass(frozen=True)
class _PendingDraw:
    order: RenderOrder
    item: RenderItem


@dataclass(frozen=True)
class _PendingCapture:
    order: RenderOrder
    request: BackBufferCopyRequest


@dataclass(frozen=True)
class _PendingScreenDraw:
    order: RenderOrder
    request: ScreenTextureDrawRequest


_Pending: TypeAlias = _PendingDraw | _PendingCapture | _PendingScreenDraw


class RenderPlanBuilder:
    """Build a deterministic render plan without backend state.

    The builder accepts already-resolved world transforms from Expra's
    canonical extraction path. It does not traverse Scene, calculate hierarchy
    transforms, or inspect backend surfaces.

    When the first screen-texture consumer for a capture slot appears before an
    explicit capture, the builder inserts an automatic full-viewport capture
    immediately before that consumer. This preserves the useful Godot behavior
    where a material that reads the screen texture causes a copy on demand.

    Explicit captures replace the snapshot in their named slot. Draws after a
    capture do not implicitly invalidate it; the snapshot intentionally remains
    frozen until another capture updates that slot.
    """

    def __init__(self) -> None:
        self._pending: list[_Pending] = []

    @classmethod
    def from_frame(
        cls,
        frame: RenderFrame,
        context: RenderContext | None = None,
    ) -> RenderPlan:
        """Convert a frame's ordered neutral submissions into a render plan."""
        builder = cls()
        submissions = frame.submissions or frame.items
        for insertion_index, submission in enumerate(submissions):
            if isinstance(submission, RenderItem):
                if context is not None and not submission.is_visible(context):
                    continue
                builder.add_item(submission, insertion_index=insertion_index)
                continue

            if not isinstance(submission, RenderEffect):
                raise TypeError(
                    f"unsupported submission type: {type(submission).__name__}"
                )

            request = submission.request
            if isinstance(request, BackBufferCopyRequest):
                builder.add_capture(
                    request,
                    phase=submission.phase,
                    layer=submission.layer,
                    insertion_index=insertion_index,
                )
            elif isinstance(request, ScreenTextureDrawRequest):
                builder.add_screen_texture(
                    request,
                    phase=submission.phase,
                    layer=submission.layer,
                    insertion_index=insertion_index,
                )
            else:
                raise TypeError(
                    f"unsupported render effect request type: {type(request).__name__}"
                )

        return builder.build()

    def add_item(self, item: RenderItem, *, insertion_index: int) -> None:
        self._pending.append(
            _PendingDraw(RenderOrder.from_item(item, insertion_index), item)
        )

    def add_capture(
        self,
        request: BackBufferCopyRequest,
        *,
        phase: RenderPhase,
        layer: int,
        insertion_index: int,
    ) -> None:
        if request.mode is BackBufferCopyMode.DISABLED:
            return
        self._pending.append(
            _PendingCapture(
                RenderOrder.from_effect(
                    phase,
                    layer,
                    request.transform,
                    insertion_index,
                ),
                request,
            )
        )

    def add_screen_texture(
        self,
        request: ScreenTextureDrawRequest,
        *,
        phase: RenderPhase,
        layer: int,
        insertion_index: int,
    ) -> None:
        self._pending.append(
            _PendingScreenDraw(
                RenderOrder.from_effect(
                    phase,
                    layer,
                    request.transform,
                    insertion_index,
                ),
                request,
            )
        )

    def extend_items(
        self,
        items: Iterable[RenderItem],
        *,
        first_insertion_index: int = 0,
    ) -> None:
        for index, item in enumerate(items, start=first_insertion_index):
            self.add_item(item, insertion_index=index)

    def build(self) -> RenderPlan:
        pending = sorted(self._pending, key=lambda entry: entry.order)
        operations: list[RenderOperation] = []
        capture_has_mipmaps: dict[str, bool] = {}
        needs_capture = False
        needs_screen = False
        needs_mipmaps = False

        for entry in pending:
            if isinstance(entry, _PendingDraw):
                operations.append(DrawItemOp(entry.order, entry.item))
                continue

            if isinstance(entry, _PendingCapture):
                operations.append(CaptureScreenOp(entry.order, entry.request))
                capture_has_mipmaps[entry.request.capture_id] = False
                needs_capture = True
                continue

            request = entry.request
            needs_capture = True
            needs_screen = True

            if request.capture_id not in capture_has_mipmaps:
                operations.append(
                    CaptureScreenOp(
                        entry.order,
                        BackBufferCopyRequest(
                            entity_id=f"__auto_capture__:{request.entity_id}",
                            capture_id=request.capture_id,
                            mode=BackBufferCopyMode.VIEWPORT,
                            transform=Transform(),
                        ),
                        automatic=True,
                    )
                )
                capture_has_mipmaps[request.capture_id] = False

            if request.usage.uses_mipmaps and not capture_has_mipmaps[request.capture_id]:
                operations.append(
                    GenerateScreenMipmapsOp(entry.order, request.capture_id)
                )
                capture_has_mipmaps[request.capture_id] = True
                needs_mipmaps = True

            operations.append(DrawScreenTextureOp(entry.order, request))

        return RenderPlan(
            tuple(operations),
            ScreenPipelineRequirements(
                screen_capture=needs_capture,
                screen_texture=needs_screen,
                screen_texture_mipmaps=needs_mipmaps,
            ),
        )
