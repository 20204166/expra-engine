"""Backend-neutral normal-map settings and scalar reference math."""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
from pathlib import PurePosixPath
from typing import Any, SupportsFloat, cast

from expra_engine.filesystem import ResourceId, ResourceService

__all__ = (
    "MAX_NORMAL_STRENGTH",
    "NormalMapEncoding",
    "NormalMapMode",
    "NormalMapResolution",
    "NormalMapResolutionStatus",
    "NormalMapResolver",
    "NormalYConvention",
    "coerce_normal_map_enums",
    "decode_normal_sample",
    "normal_texture_sources",
    "validate_normal_strength",
    "validate_normal_texture_id",
)

MAX_NORMAL_STRENGTH = 4.0


class NormalMapMode(StrEnum):
    DISABLED = "disabled"
    EXPLICIT = "explicit"
    AUTO_PAIR = "auto_pair"


class NormalYConvention(StrEnum):
    OPENGL = "opengl"
    DIRECTX = "directx"


class NormalMapEncoding(StrEnum):
    RGB_XYZ = "rgb_xyz"
    RG_XY = "rg_xy"


class NormalMapResolutionStatus(StrEnum):
    DISABLED = "disabled"
    RESOLVED = "resolved"
    MISSING = "missing"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class NormalMapResolution:
    base_texture_id: str
    normal_texture_id: str | None
    status: NormalMapResolutionStatus
    content_identity: tuple[int, str] | None = None
    detail: str | None = None


class NormalMapResolver:
    """Own exact sibling-pair policy and inspect candidates through ResourceService."""

    _IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpg", ".jpeg", ".png", ".tga", ".webp"})

    def __init__(self, resources: ResourceService, *, max_candidates: int = 1024) -> None:
        if max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        self._resources = resources
        self._max_candidates = max_candidates
        self._candidates: OrderedDict[str, str | None] = OrderedDict()

    @property
    def cache_entries(self) -> int:
        return len(self._candidates)

    def clear(self) -> None:
        self._candidates.clear()

    def texture_id_for(
        self,
        base_texture_id: str,
        mode: NormalMapMode | str,
        *,
        explicit_texture_id: str | None = None,
    ) -> str | None:
        """Return the explicit ID or exact `<stem>_normal` sibling logical ID."""
        try:
            selected_mode = NormalMapMode(mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported normal-map mode") from exc
        if selected_mode is NormalMapMode.DISABLED:
            return None
        if selected_mode is NormalMapMode.EXPLICIT:
            return validate_normal_texture_id(explicit_texture_id)

        base = ResourceId.parse(base_texture_id)
        base_id = str(base)
        if base_id in self._candidates:
            self._candidates.move_to_end(base_id)
            return self._candidates[base_id]
        source_path = PurePosixPath(base.path)
        suffix = source_path.suffix
        candidate: str | None = None
        if suffix.casefold() in self._IMAGE_SUFFIXES:
            candidate_path = source_path.with_name(f"{source_path.stem}_normal{suffix}")
            candidate = str(ResourceId(base.scheme, base.namespace, candidate_path.as_posix()))
        self._remember_candidate(str(base), candidate)
        return candidate

    def inspect(
        self,
        base_texture_id: str,
        mode: NormalMapMode | str,
        *,
        explicit_texture_id: str | None = None,
    ) -> NormalMapResolution:
        """Check the selected resource through the canonical service without decoding it."""
        try:
            selected_mode = NormalMapMode(mode)
            base_id = str(ResourceId.parse(base_texture_id))
        except (TypeError, ValueError) as exc:
            return NormalMapResolution(
                str(base_texture_id), None, NormalMapResolutionStatus.INVALID, detail=str(exc)
            )
        if selected_mode is NormalMapMode.DISABLED:
            return NormalMapResolution(base_id, None, NormalMapResolutionStatus.DISABLED)
        try:
            normal_id = self.texture_id_for(
                base_id, selected_mode, explicit_texture_id=explicit_texture_id
            )
        except (TypeError, ValueError) as exc:
            return NormalMapResolution(
                base_id, None, NormalMapResolutionStatus.INVALID, detail=str(exc)
            )
        if normal_id is None:
            return NormalMapResolution(
                base_id,
                None,
                NormalMapResolutionStatus.INVALID,
                detail="base texture has no supported auto-pair extension",
            )
        try:
            self._resources.metadata(base_id)
        except FileNotFoundError as exc:
            return NormalMapResolution(
                base_id,
                normal_id,
                NormalMapResolutionStatus.MISSING,
                detail=f"base resource missing: {exc}",
            )
        except (OSError, ValueError) as exc:
            return NormalMapResolution(
                base_id,
                normal_id,
                NormalMapResolutionStatus.INVALID,
                detail=f"base resource invalid: {exc}",
            )
        for candidate in self._resolution_candidates(selected_mode, base_id, normal_id):
            try:
                metadata = self._resources.metadata(candidate)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as exc:
                return NormalMapResolution(
                    base_id,
                    str(candidate),
                    NormalMapResolutionStatus.INVALID,
                    detail=str(exc),
                )
            return NormalMapResolution(
                base_id,
                str(candidate),
                NormalMapResolutionStatus.RESOLVED,
                content_identity=(int(metadata.size), str(metadata.content_hash)),
            )
        return NormalMapResolution(
            base_id,
            normal_id,
            NormalMapResolutionStatus.MISSING,
            detail=str(self._missing_detail(normal_id)),
        )

    def _resolution_candidates(
        self,
        mode: NormalMapMode,
        base_id: str,
        primary: str,
    ) -> tuple[ResourceId, ...]:
        """Ordered auto-pair candidates: same-extension first, then ``_normal.png``.

        The canonical generated normal is always PNG, so a ``.jpg``/``.webp``
        albedo still pairs with its generated ``<stem>_normal.png`` sibling.
        Same-extension user-authored normals take precedence.
        """
        candidates: list[ResourceId] = [ResourceId.parse(primary)]
        if mode is NormalMapMode.AUTO_PAIR:
            base = ResourceId.parse(base_id)
            source_path = PurePosixPath(base.path)
            if source_path.suffix.casefold() != ".png":
                candidates.append(
                    ResourceId(
                        base.scheme,
                        base.namespace,
                        source_path.with_name(f"{source_path.stem}_normal.png").as_posix(),
                    )
                )
        return tuple(candidates)

    def _missing_detail(self, normal_id: str) -> str:
        return f"no paired normal found; expected {normal_id}"

    def register_dependency(self, base_texture_id: str, normal_texture_id: str) -> None:
        """Register a resolved pair for export/invalidation dependency closure."""
        base_id = ResourceId.parse(base_texture_id)
        normal_id = ResourceId.parse(normal_texture_id)
        self._resources.register_dependencies(base_id, (normal_id,))

    def _remember_candidate(self, base_id: str, candidate: str | None) -> None:
        while self._candidates and len(self._candidates) >= self._max_candidates:
            self._candidates.popitem(last=False)
        self._candidates[base_id] = candidate


def normal_texture_sources(entity: object) -> tuple[tuple[str, str], ...]:
    """Return the canonical eligible texture sources for one Entity."""
    from expra_engine.runtime.animated_sprite_2d import AnimatedSprite2DComponent
    from expra_engine.runtime.visual_components import SpriteComponent

    visuals: list[tuple[str, str]] = []
    for component in getattr(entity, "components", ()):
        if isinstance(component, SpriteComponent) and component.asset:
            visuals.append(("Sprite", component.asset))
        elif isinstance(component, AnimatedSprite2DComponent):
            for animation_name in component.frames.names:
                animation = component.frames.get(animation_name)
                visuals.extend(
                    (f"Animation {animation_name} frame {index}", frame.asset_id)
                    for index, frame in enumerate(animation.frames)
                )
    return tuple(dict.fromkeys(visuals))


def coerce_normal_map_enums(
    mode: NormalMapMode | str,
    y_convention: NormalYConvention | str,
    encoding: NormalMapEncoding | str,
) -> tuple[NormalMapMode, NormalYConvention, NormalMapEncoding]:
    """Coerce the three normal-map enum fields together.

    Single owner for the shared mode/convention/encoding coercion used by both
    ``NormalMapDescriptor`` and ``MaterialComponent`` so their error semantics
    cannot drift.
    """
    try:
        return (
            NormalMapMode(mode),
            NormalYConvention(y_convention),
            NormalMapEncoding(encoding),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported normal-map mode, convention or encoding") from exc


def validate_normal_texture_id(value: str | None) -> str | None:
    """Validate and canonicalize a logical resource ID, never a filesystem path."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("normal_texture_id must be a logical resource ID")
    if value == "":
        return None
    try:
        return str(ResourceId.parse(value))
    except ValueError as exc:
        raise ValueError("normal_texture_id must be a valid logical resource ID") from exc


def validate_normal_strength(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("normal_strength must be between 0 and 4")
    try:
        strength = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("normal_strength must be between 0 and 4") from exc
    if not math.isfinite(strength) or not 0.0 <= strength <= MAX_NORMAL_STRENGTH:
        raise ValueError("normal_strength must be between 0 and 4")
    return strength


def decode_normal_sample(
    red: SupportsFloat,
    green: SupportsFloat,
    blue: SupportsFloat,
    *,
    encoding: NormalMapEncoding | str,
    convention: NormalYConvention | str,
    strength: float,
) -> tuple[float, float, float]:
    """Decode one 8-bit-style texel into a normalized canonical tangent normal.

    Channels are linear data in the inclusive ``[0, 255]`` range. Alpha is not
    part of the direction. This deliberately small scalar function is also the
    oracle for any vectorized renderer implementation.
    """
    try:
        map_encoding = NormalMapEncoding(encoding)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported normal-map encoding") from exc
    try:
        y_convention = NormalYConvention(convention)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported normal-map Y convention") from exc
    amount = validate_normal_strength(strength)

    channels = (red, green, blue)
    if any(
        isinstance(channel, bool)
        or not isinstance(channel, Real)
        or not math.isfinite(float(channel))
        or not 0.0 <= float(channel) <= 255.0
        for channel in channels
    ):
        raise ValueError("normal-map channels must be finite numbers in [0, 255]")

    if amount == 0.0:
        return (0.0, 0.0, 1.0)

    x = float(red) / 255.0 * 2.0 - 1.0
    y = float(green) / 255.0 * 2.0 - 1.0
    if y_convention is NormalYConvention.DIRECTX:
        y = -y
    x *= amount
    y *= amount

    if map_encoding is NormalMapEncoding.RGB_XYZ:
        z = float(blue) / 255.0 * 2.0 - 1.0
    else:
        xy_squared = x * x + y * y
        if xy_squared > 1.0:
            xy_length = math.sqrt(xy_squared)
            x /= xy_length
            y /= xy_length
            z = 0.0
        else:
            z = math.sqrt(max(0.0, 1.0 - xy_squared))

    length = math.hypot(x, y, z)
    if not math.isfinite(length) or length <= 1e-12:
        return (0.0, 0.0, 1.0)
    return (x / length, y / length, z / length)
