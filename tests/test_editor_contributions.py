"""Tests for the opt-in declarative editor contribution metadata."""

from __future__ import annotations

import unittest

from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.editor.contributions import (
    ContributionRegistry,
    EditorActionSpec,
    EditorContext,
    MenuContribution,
    ShortcutContribution,
    ShortcutRegistry,
    ToolbarContribution,
)


class Feature:
    def __init__(
        self,
        feature_id: str,
        actions: tuple[EditorActionSpec, ...],
        shortcuts: tuple[ShortcutContribution, ...] = (),
    ) -> None:
        self.feature_id = feature_id
        self.actions = actions
        self.menus = ()
        self.toolbars = ()
        self.shortcuts = shortcuts


class EditorContributionMetadataTests(unittest.TestCase):
    def test_action_spec_preserves_callback_and_enabled_state(self) -> None:
        def callback() -> None:
            return None

        spec = EditorActionSpec("editor.example", callback, enabled=False)

        self.assertEqual(spec.action_id, "editor.example")
        self.assertIs(spec.callback, callback)
        self.assertFalse(spec.enabled)

    def test_surface_metadata_points_to_one_action(self) -> None:
        menu = MenuContribution("File", "Example", "editor.example", order=2)
        toolbar = ToolbarContribution("editor.example", "Example", style_role="neutral")
        shortcut = ShortcutContribution("<Control-e>", "editor.example")

        self.assertEqual(menu.action_id, toolbar.action_id)
        self.assertEqual(toolbar.action_id, shortcut.action_id)
        self.assertEqual(menu.order, 2)
        self.assertEqual(toolbar.style_role, "neutral")

    def test_context_is_explicit_and_immutable(self) -> None:
        context = EditorContext(engine="engine", actions="actions", ui="ui")

        self.assertEqual(context.engine, "engine")
        self.assertEqual(context.actions, "actions")
        with self.assertRaises(AttributeError):
            context.engine = "other"  # type: ignore[misc]


class ContributionRegistryTests(unittest.TestCase):
    def test_register_delegates_action_execution_to_button_coordinator(self) -> None:
        calls: list[str] = []
        actions = ButtonCoordinator()
        registry = ContributionRegistry(actions)
        feature = Feature(
            "example",
            (EditorActionSpec("editor.example", lambda: calls.append("called")),),
        )

        registry.register(feature)
        self.assertTrue(actions.dispatch("editor.example"))
        self.assertEqual(calls, ["called"])

    def test_duplicate_action_fails_before_partial_registration(self) -> None:
        actions = ButtonCoordinator()
        actions.register("existing", lambda: None)
        registry = ContributionRegistry(actions)
        feature = Feature(
            "example",
            (
                EditorActionSpec("new", lambda: None),
                EditorActionSpec("existing", lambda: None),
            ),
        )

        with self.assertRaises(ValueError):
            registry.register(feature)
        self.assertEqual(actions.registered_ids(), ("existing",))

    def test_unregister_is_idempotent_and_removes_owned_actions(self) -> None:
        actions = ButtonCoordinator()
        registry = ContributionRegistry(actions)
        feature = Feature("example", (EditorActionSpec("editor.example", lambda: None),))
        registry.register(feature)

        registry.unregister("example")
        registry.unregister("example")
        self.assertFalse(actions.dispatch("editor.example"))

    def test_feature_shortcut_conflict_does_not_register_actions(self) -> None:
        actions = ButtonCoordinator()
        shortcuts = ShortcutRegistry()
        shortcuts.register(ShortcutContribution("<Control-z>", "undo"))
        registry = ContributionRegistry(actions, shortcuts=shortcuts)
        feature = Feature(
            "example",
            (EditorActionSpec("editor.example", lambda: None),),
            (ShortcutContribution("<Control-z>", "editor.example"),),
        )

        with self.assertRaises(ValueError):
            registry.register(feature)
        self.assertEqual(actions.registered_ids(), ())

    def test_shortcuts_normalize_and_reject_duplicates(self) -> None:
        shortcuts = ShortcutRegistry()
        shortcuts.register(ShortcutContribution(" <Control-z> ", "undo"))

        self.assertEqual(shortcuts.registered_sequences(), ("<Control-z>",))
        with self.assertRaises(ValueError):
            shortcuts.register(ShortcutContribution("<Control-z>", "redo"))

    def test_shortcut_dispatch_respects_disabled_action(self) -> None:
        actions = ButtonCoordinator()
        calls: list[str] = []
        actions.register("undo", lambda: calls.append("undo"), enabled=False)
        shortcuts = ShortcutRegistry()
        shortcuts.register(ShortcutContribution("<Control-z>", "undo"))

        self.assertFalse(shortcuts.dispatch("<Control-z>", actions))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
