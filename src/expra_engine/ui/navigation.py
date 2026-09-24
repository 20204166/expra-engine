"""In-editor panel routing.

Adapted from System Analyzer maintenance/ui/navigation.py (PageRouter).

Removed: SA import of CachePolicy (re-imported from expra_engine).
The router manages retained editor panels without destroying them on switch.

Navigation (``show``/``is_mapped``) and data freshness (``register_loader``/
``refresh``) are deliberately separate responsibilities: showing an
already-active panel is a pure no-op that never triggers a reload, and a
hidden panel's data can be refreshed independently of its visibility. This
mirrors the source PageRouter's show()/refresh() split rather than Engine's
earlier prototype, which triggered a panel's loader automatically from
``show()`` -- that coupling has been removed since nothing in the tree
depended on it (``PanelRouter`` currently has no production caller; see the
class docstring below).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from expra_engine.coordinators.app_coordinator import CachePolicy

PanelBuilder = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class PanelSpec:
    """Declarative registration for one named editor panel."""

    key: str
    build: PanelBuilder


class PanelRouter:
    """Register named panels once and switch between the retained frames.

    Panel frames are built exactly once and kept alive; only visibility
    changes on navigation so scroll positions, Tk variables, and focus
    state are preserved across switches.

    Status: this is a reusable navigation primitive with no production
    caller in the current editor composition root as of this writing.
    Hierarchy, inspector, viewport and console are simultaneously visible
    layout panes (not mutually exclusive routed pages) and must not be
    forced through this router. It exists for a future retained-page flow
    that needs mutually-exclusive switching; do not delete it as dead code.
    """

    def __init__(self, host: Any, *, coordinator: Any = None) -> None:
        self._host = host
        self._coordinator = coordinator
        self._panels: dict[str, Any] = {}
        self._loaders: dict[str, tuple[Callable[[], Any], Callable[[Any], None], CachePolicy]] = {}
        self._active_key: str | None = None

    @property
    def host(self) -> Any:
        return self._host

    @property
    def active_key(self) -> str | None:
        return self._active_key

    @property
    def registered_keys(self) -> tuple[str, ...]:
        return tuple(self._panels)

    def register(self, spec: PanelSpec) -> Any:
        """Build one panel immediately and retain it without packing it.

        The builder runs exactly once, receives the router host as its
        parent, and must not pack the returned panel root (the router owns
        panel visibility).
        """
        if not spec.key:
            raise ValueError("Panel key cannot be empty")
        if spec.key in self._panels:
            raise ValueError(f"Panel already registered: {spec.key}")
        panel = spec.build(self._host)
        self._panels[spec.key] = panel
        return panel

    def register_loader(
        self,
        key: str,
        loader: Callable[[], Any],
        on_loaded: Callable[[Any], None],
        cache_policy: CachePolicy = CachePolicy.STALE_WHILE_REFRESH,
    ) -> None:
        """Attach a heavy-data loader to one panel.

        When the router has a coordinator, ``refresh`` runs this loader
        through it (coalesced, cached, delivered on the UI thread) and feeds
        every result to ``on_loaded``. Re-registering the same key replaces
        its loader.
        """
        if key not in self._panels:
            raise KeyError(f"Unknown panel: {key}")
        self._loaders[key] = (loader, on_loaded, cache_policy)

    def refresh(self, key: str) -> int | None:
        """Redraw a panel from its cached data and re-run it in the background.

        The last cached result (if any) is applied immediately through
        ``on_loaded``; a fresh loader run is then triggered through the
        coordinator and coalesced with any run already in flight. Returns
        the run generation, or ``None`` when no loader or coordinator is
        present or the trigger was coalesced. Refreshing does not require
        the panel to be visible -- visibility and data freshness are
        independent.
        """
        entry = self._loaders.get(key)
        if entry is None or self._coordinator is None:
            return None
        loader, on_loaded, cache_policy = entry

        def task_factory(_cancel_event: Any, _progress: Any) -> Any:
            return loader()

        return self._coordinator.run(
            f"panel:{key}",
            task_factory,
            on_result=lambda _key, result: on_loaded(result),
            cache_policy=cache_policy,
        )

    def show(self, key: str) -> Any:
        """Map the named panel, hiding the current one.

        The destination is resolved and validated before anything is
        hidden, so an unknown key raises ``KeyError`` and leaves the
        current panel mapped. Showing the already-active panel is a no-op
        (it is not re-packed and no loader runs). If packing the
        destination fails, the previous panel is restored (best effort --
        a previous panel that fails to restore does not mask the original
        packing failure) and the original exception propagates; active_key
        is only updated after a successful pack.
        """
        if key not in self._panels:
            raise KeyError(f"Unknown panel: {key}")
        if key == self._active_key:
            return self._panels[key]

        destination = self._panels[key]
        previous_key = self._active_key
        previous_panel = self._panels[previous_key] if previous_key is not None else None

        # Hide the current panel before showing the new one. Best-effort: a
        # previous panel that was externally destroyed must not block
        # switching to a fresh destination.
        if previous_panel is not None:
            with contextlib.suppress(Exception):
                previous_panel.pack_forget()

        try:
            destination.pack(fill="both", expand=True)
        except Exception:
            if previous_panel is not None:
                with contextlib.suppress(Exception):
                    previous_panel.pack(fill="both", expand=True)
            raise

        self._active_key = key
        return destination

    def get_panel(self, key: str) -> Any:
        """Return a retained panel frame, raising for an unknown key."""
        try:
            return self._panels[key]
        except KeyError as error:
            raise KeyError(f"Unknown panel: {key}") from error

    def is_mapped(self, key: str) -> bool:
        return self._active_key == key
