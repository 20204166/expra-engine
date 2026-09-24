"""Selection invariants for button groups."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ButtonGroupState:
    options: list[str]
    min_selection: int = 1
    max_selection: int = 1
    _selected: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if len(set(self.options)) != len(self.options):
            raise ValueError("options must be unique")
        if self.min_selection < 0:
            raise ValueError("min_selection must be >= 0")
        if self.max_selection < 0:
            raise ValueError("max_selection must be >= 0")
        if self.max_selection and self.max_selection < self.min_selection:
            raise ValueError("max_selection must be >= min_selection or 0")
        if self.min_selection > len(self.options):
            raise ValueError("min_selection cannot exceed the number of options")
        self._selected.update(self.options[: self.min_selection])

    @property
    def selected(self) -> frozenset[str]:
        return frozenset(self._selected)

    def select(self, option: str) -> None:
        self._validate_option(option)
        if option in self._selected:
            return
        if self.max_selection and len(self._selected) >= self.max_selection:
            # Eviction follows declared option order, not selection/insertion
            # order: the first selected member in `options` order is dropped.
            oldest = next(item for item in self.options if item in self._selected)
            self._selected.remove(oldest)
        self._selected.add(option)

    def deselect(self, option: str) -> None:
        self._validate_option(option)
        if len(self._selected) > self.min_selection:
            self._selected.discard(option)

    def _validate_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unknown option: {option!r}")


__all__ = ["ButtonGroupState"]
