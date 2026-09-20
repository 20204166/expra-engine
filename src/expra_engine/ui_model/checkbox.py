"""Renderer-neutral checkbox state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckboxState:
    label: str = ""
    checked: bool = False

    def toggle(self) -> None:
        self.checked = not self.checked


__all__ = ["CheckboxState"]
