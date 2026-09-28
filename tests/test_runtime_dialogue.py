import importlib
import sys
import unittest
from textwrap import dedent

from expra_engine.runtime.dialogue import (
    BranchLimitError,
    DialogueAction,
    DialogueCondition,
    DialogueParseError,
    DialogueSession,
    TerminalDialogueError,
    parse_dialogue,
)


class RuntimeDialogueTests(unittest.TestCase):
    def test_runtime_dialogue_does_not_import_editor_modules(self) -> None:
        removed_editor = {
            name: module
            for name, module in sys.modules.items()
            if name == "expra_engine.editor" or name.startswith("expra_engine.editor.")
        }
        original_dialogue = sys.modules.pop("expra_engine.runtime.dialogue", None)
        for name in removed_editor:
            del sys.modules[name]
        try:
            importlib.import_module("expra_engine.runtime.dialogue")

            self.assertFalse(
                any(
                    module_name == "expra_engine.editor"
                    or module_name.startswith("expra_engine.editor.")
                    for module_name in sys.modules
                )
            )
            core_safe_expression = importlib.import_module("expra_engine.core.safe_expression")
            editor_safe_expression = importlib.import_module("expra_engine.editor.safe_expression")
            self.assertIs(editor_safe_expression.ExpressionError, core_safe_expression.ExpressionError)
            self.assertIs(editor_safe_expression.evaluate, core_safe_expression.evaluate)
            self.assertEqual(editor_safe_expression.evaluate("2 + 2"), 4)
        finally:
            for name in tuple(sys.modules):
                if (
                    name == "expra_engine.editor" or name.startswith("expra_engine.editor.")
                ) and name not in removed_editor:
                    del sys.modules[name]
            sys.modules.update(removed_editor)
            if original_dialogue is not None:
                sys.modules["expra_engine.runtime.dialogue"] = original_dialogue

    def test_parses_typed_nodes_choices_conditions_and_actions(self) -> None:
        graph = parse_dialogue(
            dedent(
                """
            Welcome
                * Open the door (if has_key)
                    The door opens. (gold += 2)
                * Leave (gold -= 1)
            """
            )
        )

        root = graph.start
        self.assertEqual(root.pages, ("Welcome",))
        self.assertEqual(len(root.choices), 2)
        self.assertIsInstance(root.choices[0].condition, DialogueCondition)
        self.assertIsInstance(root.choices[1].action, DialogueAction)

    def test_missing_condition_variables_are_explicit(self) -> None:
        graph = parse_dialogue("Start\n    * Continue (if known)")
        session = DialogueSession(graph, {})
        with self.assertRaises(KeyError):
            session.available_choices()

    def test_choice_applies_only_typed_actions_and_has_terminal_state(self) -> None:
        graph = parse_dialogue("Start\n    * Finish (gold += 2)")
        session = DialogueSession(graph, {"gold": 1})

        next_node = session.choose(0)

        self.assertEqual(session.variables["gold"], 3)
        self.assertTrue(next_node.terminal)
        self.assertTrue(session.finished)
        with self.assertRaises(TerminalDialogueError):
            session.choose(0)

    def test_rejects_malformed_indentation_and_excessive_branches(self) -> None:
        with self.assertRaises(DialogueParseError):
            parse_dialogue("Start\n  * Bad indentation")

        graph = parse_dialogue("Start\n    * One\n    * Two")
        with self.assertRaises(BranchLimitError):
            DialogueSession(graph, {}, max_choices=1).available_choices()


if __name__ == "__main__":
    unittest.main()
