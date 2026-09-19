"""Reusable presentation primitives for the editor UI.

Adapted from System Analyzer maintenance/ui/layout.py.

Removed: thermal_graph import, SA-specific wraplength helpers.
Preserved: resize_aware, fit_wrap_to_width, clear_children, make_scrollable_frame.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from typing import Any


def clear_children(container: Any) -> None:
    """Destroy the direct widget children of a presentation container."""
    for child in tuple(container.winfo_children()):
        child.destroy()


def resize_aware(widget: Any, handler: Callable[[Any], None]) -> Callable[[Any], None]:
    """Coalesce one widget's ``<Configure>`` events into per-frame layout calls.

    Rapid window resizes fire many ``<Configure>`` events; this helper runs
    ``handler(widget)`` at most once per idle cycle so dependent layout
    (label re-wrapping, canvas resize) never thrashes.
    """

    scheduled: dict[str, Any] = {"id": None}

    def invoke() -> None:
        scheduled["id"] = None
        with contextlib.suppress(tk.TclError):
            handler(widget)

    def on_configure(_event: Any = None) -> None:
        if scheduled["id"] is None:
            with contextlib.suppress(tk.TclError):
                scheduled["id"] = widget.after_idle(invoke)

    widget.bind("<Configure>", on_configure)
    return on_configure


def fit_wrap_to_width(
    label: Any,
    max_wrap: int,
    *,
    margin: int = 8,
    floor: int = 200,
) -> Callable[[Any], None]:
    """Return a resize handler that re-fits one label's wrap to its parent width."""

    def handler(widget: Any) -> None:
        width = widget.winfo_width()
        label.configure(wraplength=min(max_wrap, max(floor, width - margin)))

    return handler


def make_scrollable_frame(
    parent: Any,
    *,
    frame_cls: Any = None,
    canvas_cls: Any = None,
    scrollbar_cls: Any = None,
) -> tuple[Any, Any]:
    """Create a scrollable frame inside ``parent``.

    Returns ``(outer_canvas, inner_frame)`` where ``inner_frame`` is the
    frame callers should pack children into.
    """
    frame_cls = frame_cls or tk.Frame
    canvas_cls = canvas_cls or tk.Canvas
    scrollbar_cls = scrollbar_cls or tk.Scrollbar

    canvas = canvas_cls(parent, highlightthickness=0)
    scrollbar = scrollbar_cls(parent, orient="vertical", command=canvas.yview)
    inner = frame_cls(canvas)
    inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_frame_configure(_event: Any = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event: Any) -> None:
        canvas.itemconfig(inner_window, width=event.width)

    inner.bind("<Configure>", _on_frame_configure)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    return canvas, inner
