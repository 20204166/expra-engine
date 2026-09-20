"""In-editor panel routing.

Adapted from System Analyzer maintenance/ui/navigation.py (PageRouter).

Removed: SA import of CachePolicy (re-imported from expra_engine).
The router manages retained editor panels without destroying them on switch.
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
        self._loaders[key] = (loader, on_loaded, cache_policy)

    def show(self, key: str) -> bool:
        """Show the named panel and hide all others. Returns True if key found."""
        if key not in self._panels:
            return False
        for panel_key, panel in self._panels.items():
            if panel_key == key:
                with contextlib.suppress(Exception):
                    panel.pack(fill="both", expand=True)
            else:
                with contextlib.suppress(Exception):
                    panel.pack_forget()
        self._active_key = key
        loader_entry = self._loaders.get(key)
        if loader_entry is not None and self._coordinator is not None:
            loader, on_loaded, cache_policy = loader_entry
            self._coordinator.run(
                f"panel:{key}",
                lambda _cancel, _progress: loader(),
                on_result=lambda _key, result: on_loaded(result),
                cache_policy=cache_policy,
            )
        return True

    def get_panel(self, key: str) -> Any | None:
        return self._panels.get(key)
