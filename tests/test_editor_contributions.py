"""Tests for the opt-in declarative editor contribution metadata."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import cast

from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.editor.contributions import (
    ContributionRegistry,
    EditorActionSpec,
    EditorContext,
    EditorFeatureSpec,
    MenuContribution,
    MenuFactory,
    ShortcutContribution,
    ShortcutRegistry,
    ToolbarContribution,
)
from expra_engine.ui.styles import STYLE_NEUTRAL_BUTTON, STYLE_PLAY_BUTTON
from expra_engine.ui.toolbar import toolbar_style_for_role


class Feature:
    def __init__(
        self,
        feature_id: str,
        actions: tuple[EditorActionSpec, ...],
        shortcuts: tuple[ShortcutContribution, ...] = (),
    ) -> None:
        self.feature_id = feature_id
        self.actions: tuple[EditorActionSpec, ...] = actions
        self.menus: tuple[MenuContribution, ...] = ()
        self.toolbars: tuple[ToolbarContribution, ...] = ()
        self.shortcuts: tuple[ShortcutContribution, ...] = shortcuts
        self.started = 0
        self.stopped = 0
        self.fail_start = False
        self.fail_stop = False

    def start(self, _context: EditorContext) -> None:
        self.started += 1
        if self.fail_start:
            raise RuntimeError("start failed")

    def stop(self, _context: EditorContext) -> None:
        self.stopped += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")


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

    def test_feature_spec_has_explicit_empty_surface_defaults(self) -> None:
        feature = EditorFeatureSpec("example", actions=())

        self.assertEqual(feature.feature_id, "example")
        self.assertEqual(feature.menus, ())
        self.assertEqual(feature.toolbars, ())
        self.assertEqual(feature.shortcuts, ())


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

    def test_duplicate_shortcuts_within_feature_fail_before_registration(self) -> None:
        actions = ButtonCoordinator()
        shortcuts = ShortcutRegistry()
        registry = ContributionRegistry(actions, shortcuts=shortcuts)
        feature = Feature(
            "example",
            (EditorActionSpec("editor.example", lambda: None),),
            (
                ShortcutContribution("<Control-KeyPress-e>", "editor.example"),
                ShortcutContribution("<Control-e>", "editor.example"),
            ),
        )

        with self.assertRaises(ValueError):
            registry.register(feature)

        self.assertEqual(actions.registered_ids(), ())
        self.assertEqual(shortcuts.registered_sequences(), ())

    def test_registry_exposes_owned_surface_contributions(self) -> None:
        actions = ButtonCoordinator()
        registry = ContributionRegistry(actions)
        feature = EditorFeatureSpec(
            "example",
            actions=(EditorActionSpec("example", lambda: None),),
            menus=(MenuContribution("File", "Example", "example"),),
            toolbars=(ToolbarContribution("example", "Example"),),
        )

        registry.register(feature)

        self.assertEqual(registry.menu_contributions()[0].label, "Example")
        self.assertEqual(registry.toolbar_contributions()[0].action_id, "example")

    def test_invalid_style_role_fails_before_action_registration(self) -> None:
        actions = ButtonCoordinator()
        registry = ContributionRegistry(actions)
        feature = EditorFeatureSpec(
            "example",
            actions=(EditorActionSpec("example", lambda: None),),
            toolbars=(ToolbarContribution("example", "Example", style_role="missing"),),
        )

        with self.assertRaises(ValueError):
            registry.register(feature)
        self.assertEqual(actions.registered_ids(), ())

    def test_lifecycle_is_idempotent_and_start_failure_rolls_back(self) -> None:
        actions = ButtonCoordinator()
        context = EditorContext(engine=None, actions=actions, ui=None)
        registry = ContributionRegistry(actions, context=context)
        feature = Feature("example", (EditorActionSpec("example", lambda: None),))
        registry.register(feature)

        registry.start("example")
        registry.start("example")
        self.assertEqual(feature.started, 1)
        registry.unregister("example")
        self.assertEqual(feature.stopped, 1)

        failed = Feature("failed", (EditorActionSpec("failed", lambda: None),))
        failed.fail_start = True
        registry.register(failed)
        with self.assertRaises(RuntimeError):
            registry.start("failed")
        self.assertFalse(actions.dispatch("failed"))

    def test_stop_failure_does_not_block_other_features(self) -> None:
        actions = ButtonCoordinator()
        context = EditorContext(engine=None, actions=actions, ui=None)
        registry = ContributionRegistry(actions, context=context)
        first = Feature("first", (EditorActionSpec("first", lambda: None),))
        second = Feature("second", (EditorActionSpec("second", lambda: None),))
        first.fail_stop = True
        registry.register(first)
        registry.register(second)
        registry.start("first")
        registry.start("second")

        registry.stop_all()

        self.assertEqual(first.stopped, 1)
        self.assertEqual(second.stopped, 1)


class MenuFactoryTests(unittest.TestCase):
    def test_build_routes_menu_command_through_actions(self) -> None:
        class Menu:
            def __init__(self) -> None:
                self.commands: list[dict[str, object]] = []

            def add_command(self, **kwargs: object) -> None:
                self.commands.append(kwargs)

            def add_separator(self) -> None:
                self.commands.append({"separator": True})

        actions = ButtonCoordinator()
        calls: list[str] = []
        actions.register("example", lambda: calls.append("called"))
        menu = Menu()
        MenuFactory({"File": menu}).build(
            (MenuContribution("File", "Example", "example", accelerator="Ctrl+E"),),
            actions,
        )

        command = cast(Callable[[], bool], menu.commands[0]["command"])
        self.assertTrue(callable(command))
        command()
        self.assertEqual(calls, ["called"])
        self.assertEqual(menu.commands[0]["accelerator"], "Ctrl+E")


class ToolbarStyleTests(unittest.TestCase):
    def test_semantic_style_roles_resolve_to_existing_styles(self) -> None:
        self.assertEqual(toolbar_style_for_role("neutral"), STYLE_NEUTRAL_BUTTON)
        self.assertEqual(toolbar_style_for_role("play"), STYLE_PLAY_BUTTON)
        with self.assertRaises(ValueError):
            toolbar_style_for_role("missing")

    def test_shortcuts_normalize_and_reject_duplicates(self) -> None:
        shortcuts = ShortcutRegistry()
        shortcuts.register(ShortcutContribution(" <Control-KeyPress-z> ", "undo"))

        self.assertEqual(shortcuts.registered_sequences(), ("<Control-z>",))
        with self.assertRaises(ValueError):
            shortcuts.register(ShortcutContribution("<Control-z>", "redo"))

    def test_shortcut_aliases_normalize_to_one_sequence(self) -> None:
        aliases = ("<Control-Key-e>", "<Control KeyPress e>")

        for alias in aliases:
            with self.subTest(alias=alias):
                shortcuts = ShortcutRegistry()
                shortcuts.register(ShortcutContribution(alias, "first"))

                with self.assertRaises(ValueError):
                    shortcuts.register(ShortcutContribution("<Control-e>", "second"))

                self.assertEqual(shortcuts.registered_sequences(), ("<Control-e>",))

    def test_printable_shortcut_aliases_normalize_to_one_sequence(self) -> None:
        shortcuts = ShortcutRegistry()
        shortcuts.register(ShortcutContribution("e", "first"))

        with self.assertRaises(ValueError):
            shortcuts.register(ShortcutContribution("<KeyPress-e>", "second"))

        self.assertEqual(shortcuts.registered_sequences(), ("<e>",))

    def test_shortcut_normalization_preserves_punctuation_and_sequences(self) -> None:
        for sequence in ("+", ">", "[", "-"):
            with self.subTest(sequence=sequence):
                self.assertEqual(ShortcutRegistry.normalize(sequence), sequence)

        self.assertEqual(ShortcutRegistry.normalize("<KeyPress>"), "<KeyPress>")
        self.assertEqual(ShortcutRegistry.normalize("<Key>"), "<KeyPress>")
        self.assertEqual(ShortcutRegistry.normalize("<Control-KeyPress>"), "<Control-KeyPress>")
        self.assertEqual(
            ShortcutRegistry.normalize("<Control-z> <Control-x>"),
            "<Control-z> <Control-x>",
        )
        self.assertEqual(
            ShortcutRegistry.normalize("<Control-z><Control-x>"),
            "<Control-z> <Control-x>",
        )

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
