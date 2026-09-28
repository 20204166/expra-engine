"""Canonical Project launch diagnostics have bounded captured output."""

from __future__ import annotations

import importlib
import importlib.util


def test_project_launch_message_builders_distinguish_script_and_gameplay_entrypoints() -> None:
    package_spec = importlib.util.find_spec("expra_engine.messages")
    assert package_spec is not None, "core/runtime diagnostic wording has no canonical owner"
    messages = importlib.import_module("expra_engine.messages.project")

    assert messages.project_script_entrypoint_required() == (
        "project script entry point must be a non-empty relative path"
    )
    assert messages.project_script_entrypoint_outside_project() == (
        "project script entry point must remain inside the project"
    )
    assert messages.project_script_entrypoint_escapes_project() == (
        "project script entry point escapes the project"
    )
    assert messages.project_script_entrypoint_missing("__main__.py") == (
        "Script entry point not found: __main__.py"
    )
    assert messages.project_script_start_failed(
        "../outside.py", "worlds/vey.world.pb", "launcher path escapes the project"
    ) == (
        "[Editor] Could not start project launcher ../outside.py for gameplay entrypoint "
        "worlds/vey.world.pb: launcher path escapes the project"
    )
    assert messages.project_launch_failed("main.py", "worlds/main.world.pb", "permission") == (
        "[Editor] Could not launch main.py for gameplay entrypoint worlds/main.world.pb: permission"
    )
    assert messages.project_started("__main__.py", "worlds/vey.world.pb") == (
        "[Editor] Started project launcher: __main__.py; gameplay entrypoint: worlds/vey.world.pb"
    )
    assert messages.project_exited(
        7,
        "__main__.py",
        "worlds/vey.world.pb",
        "Traceback: startup failed",
    ) == (
        "[Editor] Project exited with status 7 (launcher __main__.py; "
        "gameplay entrypoint worlds/vey.world.pb)\nTraceback: startup failed"
    )
    assert messages.project_exited(0, "__main__.py", None, "ignored success output") == (
        "[Editor] Project exited (launcher __main__.py; gameplay entrypoint (not set))"
    )
    assert messages.project_entrypoint_document_unsupported() == (
        "Project entrypoint must be a Scene, Level, or World"
    )
    assert messages.project_engine_could_not_play() == "Project Engine could not enter Play"


def test_project_start_failure_bounds_untrusted_manifest_paths() -> None:
    spec = importlib.util.find_spec("expra_engine.messages.project")
    assert spec is not None
    messages = importlib.import_module("expra_engine.messages.project")

    message = messages.project_script_start_failed("x" * 10000, "y" * 10000, "bad path")

    assert len(message) <= 600
    assert "..." in message
