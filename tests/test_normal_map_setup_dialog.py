from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.editor.normal_map_generation import NormalMapGenerationPreset
from expra_engine.editor.normal_mapping_workflow import build_normal_map_setup_plan
from expra_engine.editor.qt.normal_map_setup_dialog import NormalMapSetupDialog
from tests.support.qt_app import ensure_qt_app


def test_alpha_sobel_preset_is_selectable_in_normal_map_setup(tmp_path: Path) -> None:
    ensure_qt_app()
    project = Project.create("Normal Maps", tmp_path / "project")
    resources = project.resource_service()
    plan = build_normal_map_setup_plan(Scene("Empty"), resources)
    dialog = NormalMapSetupDialog(None, SimpleNamespace(), plan, project, resources)
    try:
        index = dialog._preset_combo.findData(NormalMapGenerationPreset.ALPHA_SOBEL.value)
        assert index >= 0
        dialog._preset_combo.setCurrentIndex(index)
        assert dialog._generation_settings().preset is NormalMapGenerationPreset.ALPHA_SOBEL
    finally:
        dialog.close()
        dialog.deleteLater()
