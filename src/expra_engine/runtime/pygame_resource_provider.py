"""Decode project-owned resource bytes into cached Pygame textures."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any, cast

from expra_engine.runtime.render_diagnostics import RenderDiagnostics

__all__ = ("PygameResourceProvider",)

_LOGGER = logging.getLogger("expra_engine.runtime.pygame_renderer")


class _ResourceUnavailable:
    pass


_RESOURCE_UNAVAILABLE = _ResourceUnavailable()


class PygameResourceProvider:
    """Decode project-owned resource bytes into cached Pygame textures."""

    def __init__(self, pygame_module: Any, resources: Any) -> None:
        self._pygame = pygame_module
        self._resources = resources
        self._textures: dict[str, Any] = {}
        self._texture_identities: dict[str, tuple[int, str] | None] = {}
        self._last_failure: tuple[str, str] | None = None
        self._diagnostics = RenderDiagnostics(_LOGGER)

    @property
    def last_failure(self) -> tuple[str, str] | None:
        """Return the most recent failure from the last provider call."""
        return self._last_failure

    def reset_diagnostics(self) -> None:
        """Forget failures for resources no longer present in the current frame."""
        self._diagnostics.clear()

    def __call__(self, texture_id: str) -> Any | None:
        self._last_failure = None
        identity = self._content_identity(texture_id)
        if isinstance(identity, _ResourceUnavailable):
            self._textures.pop(texture_id, None)
            self._texture_identities.pop(texture_id, None)
            return None
        if texture_id in self._textures and (
            identity is None or self._texture_identities.get(texture_id) == identity
        ):
            return self._textures[texture_id]
        try:
            data = self._resources.read_bytes(texture_id)
        except Exception as exc:  # noqa: BLE001 - resource failures are frame-local
            self._last_failure = ("read", str(exc))
            self._diagnostics.report(
                ("texture", texture_id, "read"),
                "[Texture] Failed to read %s: %s",
                texture_id,
                exc,
            )
            return None
        try:
            texture = self._pygame.image.load(BytesIO(data))
        except Exception as exc:  # noqa: BLE001 - decoder failures are frame-local
            self._last_failure = ("decode", str(exc))
            self._diagnostics.report(
                ("texture", texture_id, "decode"),
                "[Texture] Failed to decode %s: %s",
                texture_id,
                exc,
            )
            return None
        self._textures[texture_id] = texture
        self._texture_identities[texture_id] = identity
        self._diagnostics.resolve_prefix(("texture", texture_id))
        return texture

    def _content_identity(self, texture_id: str) -> tuple[int, str] | _ResourceUnavailable | None:
        metadata = getattr(self._resources, "metadata", None)
        if not callable(metadata):
            return None
        try:
            value = cast(Any, metadata(texture_id))
            return (int(value.size), str(value.content_hash))
        except Exception as exc:  # noqa: BLE001 - metadata failures are frame-local
            self._last_failure = ("resolve", str(exc))
            self._diagnostics.report(
                ("texture", texture_id, "resolve"),
                "[Texture] Failed to resolve %s: %s",
                texture_id,
                exc,
            )
            return _RESOURCE_UNAVAILABLE
