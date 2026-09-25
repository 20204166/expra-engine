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
                EditorActionSpec("run_project", window._project_workflow.run_project),
            ),
            menus=(
                MenuContribution("File", "Run Project", "run_project", group="build", order=-1),
            ),
            toolbars=(
                ToolbarContribution("play", "▶  Play", group="runtime", style_role="play"),
                ToolbarContribution("pause", "⏸  Pause", group="runtime"),
                ToolbarContribution("stop", "⏹  Stop", group="runtime", style_role="stop"),
                ToolbarContribution("run_project", "▶▶  Run Project", group="runtime"),
            ),
        ),
        EditorFeatureSpec(
            "scene",
            actions=(
                EditorActionSpec("new_project", window._act_new_project),
                EditorActionSpec("open_project", window._act_open_project),
                EditorActionSpec("open_project_manifest", window._act_open_project_manifest),
                EditorActionSpec("close_project", window._act_close_project, enabled=False),
                EditorActionSpec("import_asset", window._act_import_asset, enabled=False),
                EditorActionSpec("configure_input", window._act_configure_input, enabled=False),
                EditorActionSpec("new_scene", window._act_new_scene),
                EditorActionSpec("open_scene", window._project_workflow.open_scene),
                EditorActionSpec("save_scene", window._act_save_scene, enabled=False),
                EditorActionSpec("save_scene_as", window._project_workflow.save_scene_as),
                EditorActionSpec("duplicate_scene", window._project_workflow.duplicate_scene),
            ),
            menus=(
                MenuContribution(
                    "File", "New Project...", "new_project", group="project", order=-2
                ),
                MenuContribution(
                    "File", "Open Project...", "open_project", group="project", order=-1
                ),
                MenuContribution(
                    "File", "Open Project Manifest...", "open_project_manifest", group="project"
                ),
                MenuContribution("File", "Close Project", "close_project", group="project"),
                MenuContribution("File", "Import Asset...", "import_asset", group="project"),
                MenuContribution("File", "Input Settings...", "configure_input", group="project"),
                MenuContribution("File", "New Scene", "new_scene", group="scene", order=0),
                MenuContribution("File", "Open Scene...", "open_scene", group="scene", order=1),
                MenuContribution("File", "Save Scene...", "save_scene", group="scene", order=2),
                MenuContribution(
                    "File", "Save Scene As...", "save_scene_as", group="scene", order=3
                ),
                MenuContribution(
                    "File", "Duplicate Scene...", "duplicate_scene", group="scene", order=4
                ),
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
                EditorActionSpec(
                    "duplicate_selection", window._act_duplicate_selection, enabled=False
                ),
            ),
            menus=(
                MenuContribution(
                    "Edit",
                    "Duplicate",
                    "duplicate_selection",
                    group="entity",
                    accelerator="Ctrl+D",
                ),
            ),
            shortcuts=(ShortcutContribution("<Control-d>", "duplicate_selection"),),
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
