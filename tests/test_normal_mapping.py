from __future__ import annotations

import math

import pytest

from expra_engine.core.project import Project
from expra_engine.runtime.normal_mapping import (
    NormalMapEncoding,
    NormalMapMode,
    NormalMapResolver,
    NormalYConvention,
    decode_normal_sample,
    validate_normal_texture_id,
)


def test_flat_normal_and_zero_strength_are_exactly_flat() -> None:
    channel_bias = 1 / 255
    decoded_length = math.sqrt(1 + 2 * channel_bias * channel_bias)
    assert decode_normal_sample(
        255,
        0,
        0,
        encoding=NormalMapEncoding.RGB_XYZ,
        convention=NormalYConvention.OPENGL,
        strength=0.0,
    ) == (0.0, 0.0, 1.0)
    assert decode_normal_sample(
        128,
        128,
        255,
        encoding=NormalMapEncoding.RGB_XYZ,
        convention=NormalYConvention.OPENGL,
        strength=1.0,
    ) == pytest.approx(
        (channel_bias / decoded_length, channel_bias / decoded_length, 1 / decoded_length),
        abs=1e-7,
    )


def test_directx_convention_inverts_green_and_strength_scales_xy() -> None:
    normal = decode_normal_sample(
        128,
        255,
        128,
        encoding=NormalMapEncoding.RGB_XYZ,
        convention=NormalYConvention.DIRECTX,
        strength=2.0,
    )

    assert normal[1] < 0.0
    assert math.sqrt(sum(channel * channel for channel in normal)) == pytest.approx(1.0)


def test_rg_decode_reconstructs_positive_z_and_clamps_xy_unit_circle() -> None:
    ordinary = decode_normal_sample(
        128,
        128,
        0,
        encoding=NormalMapEncoding.RG_XY,
        convention=NormalYConvention.OPENGL,
        strength=1.0,
    )
    overflow = decode_normal_sample(
        255,
        255,
        0,
        encoding=NormalMapEncoding.RG_XY,
        convention=NormalYConvention.OPENGL,
        strength=4.0,
    )

    assert ordinary[2] > 0.99
    assert overflow[0] == pytest.approx(2**-0.5)
    assert overflow[1] == pytest.approx(2**-0.5)
    assert overflow[2] == 0.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"red": float("nan")}, "channel"),
        ({"green": -1}, "channel"),
        ({"strength": 4.01}, "normal_strength"),
        ({"strength": float("inf")}, "normal_strength"),
    ],
)
def test_decode_rejects_invalid_scalar_inputs(kwargs, match: str) -> None:
    values = {
        "red": 128,
        "green": 128,
        "blue": 255,
        "encoding": NormalMapEncoding.RGB_XYZ,
        "convention": NormalYConvention.OPENGL,
        "strength": 1.0,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=match):
        decode_normal_sample(**values)


def test_normal_texture_id_is_a_validated_logical_resource_id() -> None:
    assert validate_normal_texture_id(None) is None
    assert validate_normal_texture_id("assets://tiles/stone_normal.png") == (
        "assets://tiles/stone_normal.png"
    )
    assert validate_normal_texture_id("package://base/stone_normal.png") == (
        "package://base/stone_normal.png"
    )

    assert validate_normal_texture_id("") is None
    for invalid in ("../stone.png", "/tmp/stone.png", "assets://../stone.png"):
        with pytest.raises(ValueError):
            validate_normal_texture_id(invalid)


def test_normal_map_modes_encodings_and_conventions_are_explicit() -> None:
    assert tuple(mode.value for mode in NormalMapMode) == (
        "disabled",
        "explicit",
        "auto_pair",
    )
    assert tuple(encoding.value for encoding in NormalMapEncoding) == ("rgb_xyz", "rg_xy")
    assert tuple(convention.value for convention in NormalYConvention) == ("opengl", "directx")


def test_auto_pair_resolver_uses_only_exact_same_folder_same_extension(tmp_path) -> None:
    project = Project.create("Normal mapping", tmp_path / "normal-project")
    base_path = project.assets_dir / "tiles" / "stone.png"
    normal_path = project.assets_dir / "tiles" / "stone_normal.png"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_bytes(b"base image")
    normal_path.write_bytes(b"normal image")
    (base_path.parent / "stone_normal_dx.png").write_bytes(b"tagged map is ignored")
    resolver = NormalMapResolver(project.resource_service())

    assert resolver.texture_id_for("assets://tiles/stone.png", NormalMapMode.AUTO_PAIR) == (
        "assets://tiles/stone_normal.png"
    )
    assert resolver.texture_id_for("assets://tiles/stone.jpg", NormalMapMode.AUTO_PAIR) == (
        "assets://tiles/stone_normal.jpg"
    )
    assert resolver.texture_id_for("assets://tiles/stone.png", NormalMapMode.EXPLICIT,
                                   explicit_texture_id="assets://other/custom.png") == (
        "assets://other/custom.png"
    )
    assert resolver.texture_id_for("assets://tiles/stone", NormalMapMode.AUTO_PAIR) is None


def test_auto_pair_inspection_reports_missing_and_resolved_resources(tmp_path) -> None:
    project = Project.create("Normal mapping", tmp_path / "normal-project")
    base_path = project.assets_dir / "stone.png"
    base_path.write_bytes(b"base image")
    resolver = NormalMapResolver(project.resource_service())

    missing = resolver.inspect("assets://stone.png", NormalMapMode.AUTO_PAIR)
    assert missing.status == "missing"
    assert missing.normal_texture_id == "assets://stone_normal.png"

    (project.assets_dir / "stone_normal.png").write_bytes(b"normal image")
    resolved = resolver.inspect("assets://stone.png", NormalMapMode.AUTO_PAIR)
    assert resolved.status == "resolved"
    assert resolved.normal_texture_id == "assets://stone_normal.png"
    assert resolved.content_identity is not None


def test_auto_pair_inspection_requires_the_base_resource_to_exist(tmp_path) -> None:
    project = Project.create("Normal mapping", tmp_path / "normal-project")
    (project.assets_dir / "stone_normal.png").write_bytes(b"normal image")
    resolver = NormalMapResolver(project.resource_service())

    result = resolver.inspect("assets://stone.png", NormalMapMode.AUTO_PAIR)

    assert result.status == "missing"
    assert result.normal_texture_id == "assets://stone_normal.png"
    assert "base" in (result.detail or "")


def test_resolved_normal_map_registers_for_dependency_closure(tmp_path) -> None:
    project = Project.create("Normal mapping", tmp_path / "normal-project")
    resources = project.resource_service()
    resolver = NormalMapResolver(resources)

    resolver.register_dependency("assets://stone.png", "assets://stone_normal.png")

    dependencies = resources.dependencies.transitive_dependencies("assets://stone.png")
    assert {str(resource_id) for resource_id in dependencies} == {
        "assets://stone_normal.png"
    }


def test_auto_pair_resolves_generated_png_for_non_png_albedo(tmp_path) -> None:
    project = Project.create("Normal mapping", tmp_path / "normal-project")
    (project.assets_dir / "wall.jpg").write_bytes(b"base image")
    resolver = NormalMapResolver(project.resource_service())

    missing = resolver.inspect("assets://wall.jpg", NormalMapMode.AUTO_PAIR)
    assert missing.status == "missing"
    assert missing.normal_texture_id == "assets://wall_normal.jpg"

    (project.assets_dir / "wall_normal.png").write_bytes(b"generated normal")
    resolved = resolver.inspect("assets://wall.jpg", NormalMapMode.AUTO_PAIR)
    assert resolved.status == "resolved"
    assert resolved.normal_texture_id == "assets://wall_normal.png"


def test_auto_pair_prefers_same_extension_over_generated_png(tmp_path) -> None:
    project = Project.create("Normal mapping", tmp_path / "normal-project")
    (project.assets_dir / "wall.jpg").write_bytes(b"base image")
    (project.assets_dir / "wall_normal.jpg").write_bytes(b"authored normal")
    (project.assets_dir / "wall_normal.png").write_bytes(b"generated normal")
    resolver = NormalMapResolver(project.resource_service())

    resolved = resolver.inspect("assets://wall.jpg", NormalMapMode.AUTO_PAIR)
    assert resolved.status == "resolved"
    assert resolved.normal_texture_id == "assets://wall_normal.jpg"


def test_auto_pair_candidate_cache_is_bounded_and_clears_on_project_change(tmp_path) -> None:
    project = Project.create("Normal mapping", tmp_path / "normal-project")
    resolver = NormalMapResolver(project.resource_service(), max_candidates=2)

    for stem in ("one", "two", "three"):
        resolver.texture_id_for(f"assets://{stem}.png", NormalMapMode.AUTO_PAIR)

    assert resolver.cache_entries == 2
    resolver.clear()
    assert resolver.cache_entries == 0
