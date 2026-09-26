"""Tests for the reusable logical-asset-to-pixel diagnostic API."""

from __future__ import annotations

import tkinter as tk
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.filesystem.errors import InvalidResourceIdError
from expra_engine.runtime import (
    TextureDiagnosticReport as ExportedTextureDiagnosticReport,
)
from expra_engine.runtime import (
    TextureDiagnosticStage as ExportedTextureDiagnosticStage,
)
from expra_engine.runtime import (
    diagnose_texture as exported_diagnose_texture,
)
from expra_engine.runtime.rendering import OrthographicCamera, RenderContext, Viewport
from expra_engine.runtime.texture_diagnostics import (
    TextureDiagnosticReport,
    TextureDiagnosticStage,
    diagnose_texture,
)
from expra_engine.runtime.visual_components import SpriteComponent
from tests.support.texture_project import make_texture_project


def test_diagnostic_values_are_immutable_and_ordered() -> None:
    stage = TextureDiagnosticStage("extract", True, "one render item")
    report = TextureDiagnosticReport(
        "assets://probe.png",
        ("probe",),
        (stage,),
        True,
        None,
        None,
    )

    assert report.stages == (stage,)
    assert report.entity_ids == ("probe",)
    with pytest.raises(FrozenInstanceError):
        stage.ok = False  # type: ignore[misc]


def test_diagnose_validates_project_and_asset_id() -> None:
    context = RenderContext(Viewport(0, 0, 160, 120))

    with pytest.raises(TypeError, match="project"):
        diagnose_texture(
            cast(Project, object()),
            Scene("probe"),
            "assets://probe.png",
            context=context,
            pygame_module=SimpleNamespace(),
        )
    with pytest.raises(InvalidResourceIdError):
        diagnose_texture(
            Project("Probe", Path("/tmp/probe")),
            Scene("probe"),
            "probe.png",
            context=context,
            pygame_module=SimpleNamespace(),
        )


def test_diagnose_reports_missing_sprite_without_touching_resources() -> None:
    result = diagnose_texture(
        Project("Probe", Path("/tmp/probe")),
        Scene("probe"),
        "assets://probe.png",
        context=RenderContext(Viewport(0, 0, 160, 120)),
        pygame_module=SimpleNamespace(),
    )

    assert not result.ok
    assert result.asset_id == "assets://probe.png"
    assert result.failed_stage == "sprite_component"
    assert result.failure_detail
    assert result.stages[-1].ok is False


def test_diagnostic_api_is_exported_from_runtime() -> None:
    assert ExportedTextureDiagnosticReport is TextureDiagnosticReport
    assert ExportedTextureDiagnosticStage is TextureDiagnosticStage
    assert exported_diagnose_texture is diagnose_texture


def test_generic_project_reports_real_png_through_rendering(tmp_path: Path) -> None:
    pygame = pytest.importorskip("pygame")
    project, scene, asset_id = make_texture_project(tmp_path)
    pygame.init()
    try:
        result = diagnose_texture(
            project,
            scene,
            asset_id,
            context=RenderContext(
                Viewport(0, 0, 160, 120), OrthographicCamera(width=10.0, height=7.5)
            ),
            pygame_module=pygame,
        )
    finally:
        pygame.quit()

    assert result.ok
    assert [stage.name for stage in result.stages] == [
        "sprite_component",
        "extract",
        "resolve",
        "read",
        "decode",
        "render",
        "pixels",
    ]
    assert result.entity_ids == ("probe",)
    assert result.mount == "project-assets"
    assert result.physical_path is not None and result.physical_path.endswith("assets/probe.png")
    assert result.byte_size is not None and result.byte_size > 0
    assert result.texture_size == (2, 2)
    assert result.cache_key == asset_id
    assert result.texture_type == "Surface"
    assert result.output_bounds is not None
    assert result.output_bounds[2] > 0 and result.output_bounds[3] > 0


def test_diagnostic_can_include_editor_presentation(tmp_path: Path, monkeypatch) -> None:
    pygame = pytest.importorskip("pygame")
    project, scene, asset_id = make_texture_project(tmp_path)

    class Image:
        def width(self) -> int:
            return 160

        def height(self) -> int:
            return 120

    captured: dict[str, object] = {}

    def bridge(_frame, _context, **kwargs):
        captured.update(kwargs)
        return Image()

    monkeypatch.setattr(
        "expra_engine.runtime.texture_diagnostics._render_editor_frame_to_tk_image", bridge
    )
    pygame.init()
    try:
        result = diagnose_texture(
            project,
            scene,
            asset_id,
            context=RenderContext(Viewport(0, 0, 160, 120)),
            pygame_module=pygame,
            image_master=object(),
        )
    finally:
        pygame.quit()

    assert result.ok
    assert result.editor_image_size == (160, 120)
    assert result.stages[-1].name == "editor_presentation"
    assert captured["image_master"] is not None


def test_generic_project_reaches_real_editor_presentation(tmp_path: Path) -> None:
    pygame = pytest.importorskip("pygame")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for real Tk editor presentation")
    project, scene, asset_id = make_texture_project(tmp_path)
    pygame.init()
    try:
        result = diagnose_texture(
            project,
            scene,
            asset_id,
            context=RenderContext(Viewport(0, 0, 160, 120)),
            pygame_module=pygame,
            image_master=root,
        )
    finally:
        pygame.quit()
        root.destroy()

    assert result.ok
    assert result.editor_image_size == (160, 120)


def test_diagnose_reports_missing_resolved_asset(tmp_path: Path) -> None:
    pygame = pytest.importorskip("pygame")
    project, scene, _asset_id = make_texture_project(tmp_path)
    sprite = scene.find_entity("probe").get_component(SpriteComponent)  # type: ignore[union-attr]
    assert sprite is not None
    sprite.asset = "assets://missing.png"

    pygame.init()
    try:
        result = diagnose_texture(
            project,
            scene,
            sprite.asset,
            context=RenderContext(Viewport(0, 0, 160, 120)),
            pygame_module=pygame,
        )
    finally:
        pygame.quit()

    assert not result.ok
    assert result.failed_stage == "resolve"


def test_diagnose_reports_png_decode_failure(tmp_path: Path) -> None:
    pygame = pytest.importorskip("pygame")
    project, scene, asset_id = make_texture_project(tmp_path)
    (project.assets_dir / "probe.png").write_bytes(b"not a PNG")

    pygame.init()
    try:
        result = diagnose_texture(
            project,
            scene,
            asset_id,
            context=RenderContext(Viewport(0, 0, 160, 120)),
            pygame_module=pygame,
        )
    finally:
        pygame.quit()

    assert not result.ok
    assert result.failed_stage == "decode"


def test_diagnose_reports_malformed_decoded_texture_size(tmp_path: Path, monkeypatch) -> None:
    project, scene, asset_id = make_texture_project(tmp_path)

    class MalformedTexture:
        def get_size(self) -> tuple[object, object]:
            return "wide", 2

    class Provider:
        last_failure = None

        def __init__(self, _pygame_module, _resources) -> None:
            pass

        def __call__(self, _asset_id: str) -> MalformedTexture:
            return MalformedTexture()

    monkeypatch.setattr("expra_engine.runtime.texture_diagnostics.PygameResourceProvider", Provider)
    backend = SimpleNamespace(
        font=SimpleNamespace(init=lambda: None),
        image=SimpleNamespace(init=lambda: None),
    )

    result = diagnose_texture(
        project,
        scene,
        asset_id,
        context=RenderContext(Viewport(0, 0, 160, 120)),
        pygame_module=backend,
    )

    assert not result.ok
    assert result.failed_stage == "decode"
    assert result.failure_detail == "decoded texture has no valid size"


def test_diagnose_reports_image_backend_initialization_failure(tmp_path: Path) -> None:
    project, scene, asset_id = make_texture_project(tmp_path)

    def fail_init() -> None:
        raise RuntimeError("image backend unavailable")

    backend = SimpleNamespace(
        font=SimpleNamespace(init=lambda: None),
        image=SimpleNamespace(init=fail_init),
    )

    result = diagnose_texture(
        project,
        scene,
        asset_id,
        context=RenderContext(Viewport(0, 0, 160, 120)),
        pygame_module=backend,
    )

    assert not result.ok
    assert result.failed_stage == "decode"
    assert result.failure_detail == "image backend initialization failed: image backend unavailable"


def test_diagnose_reports_malformed_editor_image_dimensions(tmp_path: Path, monkeypatch) -> None:
    pygame = pytest.importorskip("pygame")
    project, scene, asset_id = make_texture_project(tmp_path)

    class Image:
        def width(self) -> str:
            return "wide"

        def height(self) -> int:
            return 120

    monkeypatch.setattr(
        "expra_engine.runtime.texture_diagnostics._render_editor_frame_to_tk_image",
        lambda *_args, **_kwargs: Image(),
    )
    pygame.init()
    try:
        result = diagnose_texture(
            project,
            scene,
            asset_id,
            context=RenderContext(Viewport(0, 0, 160, 120)),
            pygame_module=pygame,
            image_master=object(),
        )
    finally:
        pygame.quit()

    assert not result.ok
    assert result.failed_stage == "editor_presentation"
    assert result.failure_detail == "editor image dimensions are invalid"


def test_diagnose_reports_when_texture_renders_outside_the_context(tmp_path: Path) -> None:
    pygame = pytest.importorskip("pygame")
    project, scene, asset_id = make_texture_project(tmp_path)
    entity = scene.find_entity("probe")
    assert entity is not None
    entity.add_component(TransformComponent(x=100.0, y=100.0))

    pygame.init()
    try:
        result = diagnose_texture(
            project,
            scene,
            asset_id,
            context=RenderContext(Viewport(0, 0, 160, 120)),
            pygame_module=pygame,
        )
    finally:
        pygame.quit()

    assert not result.ok
    assert result.failed_stage == "pixels"


def test_blacksite_sprite_assets_pass_the_same_diagnostic_api() -> None:
    pygame = pytest.importorskip("pygame")
    project = Project.load(Path(__file__).parents[1] / "examples" / "blacksite_relay")
    scene = project.load_scene()
    assets = sorted(
        {
            component.asset
            for entity in scene.entities
            for component in entity.components
            if isinstance(component, SpriteComponent) and component.visible and component.enabled
        }
    )
    pygame.init()
    try:
        reports = [
            diagnose_texture(
                project,
                scene,
                asset_id,
                context=RenderContext(
                    Viewport(0, 0, 400, 300), OrthographicCamera(width=100.0, height=75.0)
                ),
                pygame_module=pygame,
            )
            for asset_id in assets
        ]
    finally:
        pygame.quit()

    assert assets
    assert all(report.ok for report in reports)
