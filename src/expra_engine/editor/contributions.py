"""Opt-in declarative contributions for editor features.

This module contains metadata and registries only. Feature callbacks continue
to own editor behavior, while coordinators continue to own execution and
presentation safety.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EditorContext:
    """Explicit dependencies made available to an editor feature."""

    engine: Any
    actions: Any
    ui: Any
    app: Any | None = None
    project: Any | None = None


@dataclass(frozen=True, slots=True)
class EditorActionSpec:
    """Metadata and callback boundary for one stable editor action."""

    action_id: str
    callback: Callable[[], None]
    enabled: bool = True
    enabled_when: Callable[[Any], bool] | None = None


@dataclass(frozen=True, slots=True)
class MenuContribution:
    """One menu command contributed by an editor feature."""

    parent: str
    label: str
    action_id: str
    group: str = ""
    order: int = 0
    separator_before: bool = False
    accelerator: str = ""


@dataclass(frozen=True, slots=True)
class ToolbarMenuItem:
    """Typed menu row nested beneath one shared toolbar dropdown."""

    label: str
    action_id: str


@dataclass(frozen=True, slots=True)
class ToolbarContribution:
    """One toolbar button contributed by an editor feature."""

    action_id: str | None
    label: str
    group: str = ""
    order: int = 0
    style_role: str = "neutral"
    menu_items: tuple[ToolbarMenuItem, ...] = ()

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("toolbar contribution label must not be empty")
        if self.action_id is None and not self.menu_items:
            raise ValueError("toolbar contribution needs an action or nested menu items")
        if self.action_id is not None and self.menu_items:
            raise ValueError("a toolbar contribution cannot be both a button and a menu")


@dataclass(frozen=True, slots=True)
class ShortcutContribution:
    """One keyboard sequence routed to a stable action ID."""

    sequence: str
    action_id: str


class EditorFeature(Protocol):
    """Minimal explicit provider contract for a registered editor feature."""

    @property
    def feature_id(self) -> str: ...

    @property
    def actions(self) -> tuple[EditorActionSpec, ...]: ...

    @property
    def menus(self) -> tuple[MenuContribution, ...]: ...

    @property
    def toolbars(self) -> tuple[ToolbarContribution, ...]: ...

    @property
    def shortcuts(self) -> tuple[ShortcutContribution, ...]: ...


@dataclass(frozen=True, slots=True)
class EditorFeatureSpec:
    """Concrete immutable feature declaration for explicit registries."""

    feature_id: str
    actions: tuple[EditorActionSpec, ...] = ()
    menus: tuple[MenuContribution, ...] = ()
    toolbars: tuple[ToolbarContribution, ...] = ()
    shortcuts: tuple[ShortcutContribution, ...] = ()
    start: Callable[[EditorContext], None] | None = None
    stop: Callable[[EditorContext], None] | None = None


@dataclass(slots=True)
class _FeatureRecord:
    feature: EditorFeature
    action_ids: tuple[str, ...]
    shortcut_sequences: tuple[str, ...]
    menus: tuple[MenuContribution, ...]
    toolbars: tuple[ToolbarContribution, ...]
    started: bool = False


class ContributionRegistry:
    """Own opt-in feature registrations while delegating execution to actions."""

    def __init__(
        self,
        actions: Any,
        *,
        context: EditorContext | None = None,
        shortcuts: ShortcutRegistry | None = None,
        style_roles: frozenset[str] = frozenset({"neutral", "play", "stop"}),
    ) -> None:
        self._context = context
        self._actions = actions
        self._shortcuts = shortcuts or ShortcutRegistry()
        self._style_roles = style_roles
        self._features: dict[str, _FeatureRecord] = {}

    def register(self, feature: EditorFeature) -> None:
        feature_id = feature.feature_id
        if not feature_id:
            raise ValueError("Feature id cannot be empty")
        if feature_id in self._features:
            raise ValueError(f"Feature already registered: {feature_id}")

        action_ids = tuple(spec.action_id for spec in feature.actions)
        if len(action_ids) != len(set(action_ids)):
            raise ValueError(f"Feature contains duplicate action IDs: {feature_id}")
        if any(not action_id for action_id in action_ids):
            raise ValueError(f"Feature contains an empty action ID: {feature_id}")
        if any(not item.parent for item in feature.menus):
            raise ValueError(f"Feature contains a menu without a parent: {feature_id}")
        invalid_roles = {
            item.style_role for item in feature.toolbars if item.style_role not in self._style_roles
        }
        if invalid_roles:
            raise ValueError(f"Unknown toolbar style role: {sorted(invalid_roles)[0]}")
        existing_ids = set(self._actions.registered_ids())
        conflict = existing_ids.intersection(action_ids)
        if conflict:
            raise ValueError(f"Action already registered: {sorted(conflict)[0]}")
        menu_action_ids = tuple(item.action_id for item in feature.menus)
        toolbar_action_ids = tuple(
            item.action_id for item in feature.toolbars if item.action_id is not None
        )
        toolbar_menu_action_ids = tuple(
            menu_item.action_id
            for toolbar in feature.toolbars
            for menu_item in toolbar.menu_items
        )
        shortcut_action_ids = tuple(item.action_id for item in feature.shortcuts)
        referenced_ids = set(
            menu_action_ids
            + toolbar_action_ids
            + toolbar_menu_action_ids
            + shortcut_action_ids
        )
        if not referenced_ids.issubset(action_ids):
            missing = sorted(referenced_ids.difference(action_ids))[0]
            raise ValueError(f"Contribution references unknown action: {missing}")
        shortcut_sequences = tuple(
            self._shortcuts.normalize(item.sequence) for item in feature.shortcuts
        )
        if len(shortcut_sequences) != len(set(shortcut_sequences)):
            raise ValueError(f"Feature contains duplicate shortcuts: {feature_id}")
        for shortcut in feature.shortcuts:
            self._shortcuts.validate(shortcut)

        for spec in feature.actions:
            self._actions.register(spec.action_id, spec.callback, enabled=spec.enabled)
        for shortcut in feature.shortcuts:
            self._shortcuts.register(shortcut)
        self._features[feature_id] = _FeatureRecord(
            feature=feature,
            action_ids=action_ids,
            shortcut_sequences=shortcut_sequences,
            menus=feature.menus,
            toolbars=feature.toolbars,
        )

    def menu_contributions(self) -> tuple[MenuContribution, ...]:
        return tuple(item for record in self._features.values() for item in record.menus)

    def toolbar_contributions(self) -> tuple[ToolbarContribution, ...]:
        return tuple(item for record in self._features.values() for item in record.toolbars)

    def unregister(self, feature_id: str) -> None:
        record = self._features.get(feature_id)
        if record is None:
            return
        self._stop_record(record)
        self._remove_record(feature_id, record)

    def start(self, feature_id: str) -> None:
        record = self._features[feature_id]
        if record.started:
            return
        start = getattr(record.feature, "start", None)
        try:
            if start is not None:
                start(self._context)
        except Exception:
            self._remove_record(feature_id, record)
            raise
        record.started = True

    def stop_all(self) -> None:
        for feature_id, record in tuple(self._features.items()):
            self._stop_record(record)
            self._remove_record(feature_id, record)

    def _stop_record(self, record: _FeatureRecord) -> None:
        if not record.started:
            return
        stop = getattr(record.feature, "stop", None)
        record.started = False
        if stop is not None:
            try:
                stop(self._context)
            except Exception:
                LOGGER.exception("Editor feature shutdown failed")

    def _remove_record(self, feature_id: str, record: _FeatureRecord) -> None:
        self._features.pop(feature_id, None)
        for action_id in record.action_ids:
            self._actions.unregister(action_id)
        for sequence in record.shortcut_sequences:
            self._shortcuts.unregister(sequence)


class ShortcutRegistry:
    """Validate and route normalized keyboard sequences to action IDs."""

    def __init__(self) -> None:
        self._shortcuts: dict[str, str] = {}

    def register(self, shortcut: ShortcutContribution) -> None:
        sequence = self.normalize(shortcut.sequence)
        if not shortcut.action_id:
            raise ValueError("Shortcut action id cannot be empty")
        existing = self._shortcuts.get(sequence)
        if existing is not None:
            raise ValueError(f"Shortcut already registered: {sequence}")
        self._shortcuts[sequence] = shortcut.action_id

    def validate(self, shortcut: ShortcutContribution) -> None:
        sequence = self.normalize(shortcut.sequence)
        if not shortcut.action_id:
            raise ValueError("Shortcut action id cannot be empty")
        if sequence in self._shortcuts:
            raise ValueError(f"Shortcut already registered: {sequence}")

    def unregister(self, sequence: str) -> None:
        self._shortcuts.pop(self.normalize(sequence), None)

    def registered_sequences(self) -> tuple[str, ...]:
        return tuple(self._shortcuts)

    def dispatch(self, sequence: str, actions: Any) -> bool:
        action_id = self._shortcuts.get(self.normalize(sequence))
        return action_id is not None and actions.dispatch(action_id)

    @staticmethod
    def normalize(sequence: str) -> str:
        value = sequence.strip()
        if not value:
            raise ValueError("Shortcut sequence cannot be empty")
        if value.startswith("<") and value.endswith(">"):
            raise ValueError("Shortcuts must use Qt QKeySequence syntax")

        def normalize_stroke(stroke: str) -> str:
            stroke = stroke.strip()
            if not stroke:
                raise ValueError("Shortcut sequence contains an empty stroke")
            if len(stroke) == 1:
                return stroke.upper() if stroke.isalpha() else stroke

            if stroke.endswith("++"):
                parts, key = stroke[:-2].split("+"), "+"
            else:
                parts = stroke.split("+")
                key = parts.pop()
            if not key or any(not part.strip() for part in parts):
                raise ValueError(f"Invalid Qt shortcut sequence: {stroke!r}")

            aliases = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "meta": "Meta"}
            modifiers: list[str] = []
            for part in parts:
                modifier = aliases.get(part.strip().casefold())
                if modifier is None:
                    raise ValueError(f"Invalid Qt shortcut modifier: {part!r}")
                if modifier not in modifiers:
                    modifiers.append(modifier)
            modifiers.sort(key=("Ctrl", "Alt", "Shift", "Meta").index)
            key = key.upper() if len(key) == 1 and key.isalpha() else key[0].upper() + key[1:]
            return "+".join((*modifiers, key))

        strokes = [normalize_stroke(stroke) for stroke in value.split(",")]
        return ", ".join(strokes)
