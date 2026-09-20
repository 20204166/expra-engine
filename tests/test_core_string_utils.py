from __future__ import annotations

import unittest

from expra_engine.core.string_utils import (
    camel_to_snake,
    multireplace,
    snake_to_camel,
    snake_to_lower_camel,
)


class StringUtilsTests(unittest.TestCase):
    def test_camel_to_snake_handles_acronyms(self) -> None:
        self.assertEqual(camel_to_snake("CamelCase"), "camel_case")
        self.assertEqual(camel_to_snake("HTMLParser"), "html_parser")
        self.assertEqual(camel_to_snake("already_snake"), "already_snake")

    def test_snake_to_camel(self) -> None:
        self.assertEqual(snake_to_camel("my_variable_name"), "MyVariableName")
        self.assertEqual(snake_to_camel("_hidden"), "Hidden")
        self.assertEqual(snake_to_camel(""), "")

    def test_snake_to_lower_camel(self) -> None:
        self.assertEqual(snake_to_lower_camel("my_variable_name"), "myVariableName")
        self.assertEqual(snake_to_lower_camel("hello"), "hello")
        self.assertEqual(snake_to_lower_camel(""), "")

    def test_multireplace_is_single_pass(self) -> None:
        self.assertEqual(multireplace("foo bar baz", {"foo": "A", "bar": "B"}), "A B baz")
        self.assertEqual(multireplace("hello", {}), "hello")
        self.assertEqual(multireplace("aabbcc", {"aa": "X", "cc": "Z"}), "XbbZ")


if __name__ == "__main__":
    unittest.main()
