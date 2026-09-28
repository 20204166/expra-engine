"""Engine lifecycle message wording is centralized without owning lifecycle policy."""

from __future__ import annotations

import importlib
import importlib.util


def test_world_lifecycle_message_includes_phase_level_and_bounded_exception_detail() -> None:
    package_spec = importlib.util.find_spec("expra_engine.messages")
    assert package_spec is not None, "core/runtime diagnostic wording has no canonical owner"
    messages = importlib.import_module("expra_engine.messages.engine")

    assert (
        messages.world_lifecycle_failed("activation", "town", "RuntimeError", "hook failed")
        == "activation town: RuntimeError: hook failed"
    )
    assert len(messages.world_lifecycle_failed("activation", "town", "Error", "x" * 500)) <= 192


def test_world_lifecycle_diagnostic_bounds_untrusted_level_identifier() -> None:
    spec = importlib.util.find_spec("expra_engine.messages.engine")
    assert spec is not None
    messages = importlib.import_module("expra_engine.messages.engine")

    message = messages.world_lifecycle_failed("activation", "l" * 10000, "Error", "failed")

    assert len(message) <= 300
    assert "..." in message


def test_runtime_preview_failure_message_is_bounded_and_actionable() -> None:
    spec = importlib.util.find_spec("expra_engine.messages.engine")
    assert spec is not None
    messages = importlib.import_module("expra_engine.messages.engine")

    assert messages.runtime_preview_tick_failed("LookupError", "missing attack hitbox") == (
        "[Engine] Runtime preview stopped after LookupError: missing attack hitbox"
    )
    message = messages.runtime_preview_tick_failed("E" * 1000, "detail " * 1000)
    assert len(message) <= 640
    assert message.count("...") == 2
