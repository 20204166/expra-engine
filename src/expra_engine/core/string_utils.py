"""String conversion helpers used by serialization and tooling."""

from __future__ import annotations

import re


def camel_to_snake(name: str) -> str:
    """Convert CamelCase or mixedCase to snake_case."""
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    return separated.lower()


def snake_to_camel(name: str) -> str:
    """Convert snake_case to UpperCamelCase."""
    return "".join(word.capitalize() for word in name.split("_") if word)


def snake_to_lower_camel(name: str) -> str:
    """Convert snake_case to lowerCamelCase."""
    parts = [word for word in name.split("_") if word]
    if not parts:
        return ""
    return parts[0].lower() + "".join(word.capitalize() for word in parts[1:])


def multireplace(text: str, replacements: dict[str, str]) -> str:
    """Replace mapping keys in one regular-expression pass."""
    if not replacements:
        return text
    pattern = re.compile("|".join(re.escape(key) for key in replacements))
    return pattern.sub(lambda match: replacements[match.group(0)], text)


__all__ = [
    "camel_to_snake",
    "multireplace",
    "snake_to_camel",
    "snake_to_lower_camel",
]
