from __future__ import annotations

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.runtime.lighting_2d import Light2DComponent
from expra_engine.ui.editor_window import EditorWindow
from tests.support.tk_display import display_available


@pytest.mark.skipif(not display_available(), reason="no display for real Tk editor tests")
def test_view_menu_preview_lighting_toggle_only_changes_the_editor_frame(tmp_path) -> None:
    project = Project.create("Preview Lighting", tmp_path / "project")
    engine = Engine()
    window = EditorWindow(engine)
    try:
        window._project_workflow.open_loaded(Project.load(project.path))
        render_requests = []
        request_render = window._request_render

        def record_render_request(*args, **kwargs):
            render_requests.append((args, kwargs))
            return request_render(*args, **kwargs)

        window._request_render = record_render_request
        viewport_calls = []
        frame_values = []
        viewport_render = window._viewport.render

        def record_viewport_render(*args, **kwargs):
            viewport_calls.append((args, kwargs))
            result = viewport_render(*args, **kwargs)
            frame_values.append(window._viewport._target.frame.lighting_enabled)
            return result

        window._viewport.render = record_viewport_render
        menubar = window._root.nametowidget(window._root.cget("menu"))
        view_menu = window._root.nametowidget(menubar.entrycget("View", "menu"))
        scene = window._engine.edit_scene
        assert scene is not None
        original_camera_settings = scene.camera.to_dict()

        assert window._preview_lighting_var.get() is True
        view_menu.invoke(0)
        window._root.update()
        assert window._preview_lighting_var.get() is False
        for geometry in ("980x640", "1280x800", "1440x900"):
            window._root.geometry(geometry)
            window._root.update()
            window._viewport._on_resize()
            assert window._viewport._target.frame.lighting_enabled is False
        assert len(render_requests) == 1
        assert viewport_calls[-1][1]["preview_lighting"] is False
        assert frame_values[-1] is False
        assert window._viewport._target.frame.lighting_enabled is False
        assert scene.camera.to_dict() == original_camera_settings

        view_menu.invoke(0)
        window._root.update()
        assert window._preview_lighting_var.get() is True
        assert window._viewport._target.frame.lighting_enabled is True
        assert scene.camera.to_dict() == original_camera_settings

        light = scene.create_entity("Editor Light", entity_id="editor-light")
        light.add_component(TransformComponent(x=1.0, y=1.0))
        light.add_component(Light2DComponent(radius=2.0))
        window._viewport.render(
            scene,
            light.entity_id,
            selected_ids=frozenset({light.entity_id}),
            editor_overlays=True,
            preview_lighting=True,
        )
        assert window._viewport._light_gizmo is not None

        window._viewport.render(
            scene,
            light.entity_id,
            selected_ids=frozenset({light.entity_id}),
            editor_overlays=False,
            preview_lighting=None,
        )
        assert window._viewport._light_gizmo is None
        assert len(window._viewport._target.frame.lights) == 1
        assert window._viewport._pixel_image is not None

        window._viewport.render(
            scene,
            light.entity_id,
            selected_ids=frozenset({light.entity_id}),
            editor_overlays=True,
            preview_lighting=True,
        )
        assert window._viewport._light_gizmo is not None
    finally:
        window._on_close()
