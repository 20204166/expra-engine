"""Explicit built-in editor feature declarations."""

from __future__ import annotations

from typing import Any

from expra_engine.editor.contributions import (
    EditorActionSpec,
    EditorFeatureSpec,
    MenuContribution,
    ShortcutContribution,
    ToolbarContribution,
)


def build_builtin_features(window: Any) -> tuple[EditorFeatureSpec, ...]:
    """Return the stable built-in provider list for one editor window."""
    return (
        EditorFeatureSpec(
            "runtime",
            actions=(
                EditorActionSpec("play", window._act_play),
                EditorActionSpec("pause", window._act_pause),
                EditorActionSpec("stop", window._act_stop),
            ),
            toolbars=(
                ToolbarContribution("play", "▶  Play", group="runtime", style_role="play"),
                ToolbarContribution("pause", "⏸  Pause", group="runtime"),
                ToolbarContribution("stop", "⏹  Stop", group="runtime", style_role="stop"),
            ),
        ),
        EditorFeatureSpec(
            "scene",
            actions=(
                EditorActionSpec("new_scene", window._act_new_scene),
                EditorActionSpec("save_scene", window._act_save_scene),
            ),
            menus=(
                MenuContribution("File", "New Scene", "new_scene", group="scene", order=0),
                MenuContribution("File", "Save Scene...", "save_scene", group="scene", order=1),
            ),
            toolbars=(
                ToolbarContribution("new_scene", "New Scene", group="scene"),
                ToolbarContribution("save_scene", "Save", group="scene"),
            ),
        ),
        EditorFeatureSpec(
            "entity",
            actions=(
                EditorActionSpec("add_entity", window._act_add_entity),
                EditorActionSpec("delete_entity", window._act_delete_entity, enabled=False),
            ),
        ),
        EditorFeatureSpec(
            "scripting",
            actions=(
                EditorActionSpec("new_script", window._act_new_script),
                EditorActionSpec("attach_script", window._act_attach_script, enabled=False),
                EditorActionSpec("remove_script", window._act_remove_script, enabled=False),
            ),
            menus=(
                MenuContribution("File", "New Behaviour Script...", "new_script", group="scene"),
                MenuContribution(
                    "Edit", "Attach Behaviour Script...", "attach_script", group="entity"
                ),
                MenuContribution(
                    "Edit", "Remove Behaviour Script", "remove_script", group="entity"
                ),
            ),
        ),
        EditorFeatureSpec(
            "history",
            actions=(
                EditorActionSpec("undo", window._act_undo, enabled=False),
                EditorActionSpec("redo", window._act_redo, enabled=False),
            ),
            menus=(
                MenuContribution("Edit", "Undo", "undo", group="history", accelerator="Ctrl+Z"),
                MenuContribution(
                    "Edit", "Redo", "redo", group="history", order=1, accelerator="Ctrl+Y"
                ),
            ),
            shortcuts=(
                ShortcutContribution("<Control-z>", "undo"),
                ShortcutContribution("<Control-y>", "redo"),
            ),
        ),
        EditorFeatureSpec(
            "export",
            actions=(EditorActionSpec("editor.export_game", window._act_export_game),),
            menus=(
                MenuContribution(
                    "File",
                    "Export Game...",
                    "editor.export_game",
                    group="build",
                    separator_before=True,
                ),
            ),
        ),
    )
