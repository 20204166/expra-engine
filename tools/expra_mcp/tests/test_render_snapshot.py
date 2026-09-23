"""Protocol-level tests for render_snapshot / diagnostics_analyze /
render_inspect(action="compare_modes"), driven through the official mcp
Client against real projects. Some tests deliberately exercise real failure
paths (Space Pong's paddles use a "rounded_rectangle" primitive kind that
the real PygameRenderer does not support) rather than only the happy path,
since diagnostics_analyze's whole point is aggregating real failures.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import conftest
import pytest
from expra_dev_mcp.server import build_server
from mcp import Client
from mcp.types import ImageContent

BLACKSITE = "examples/blacksite_relay"
SPACE_PONG = "examples/space_pong"


@pytest.fixture
def server():
    return build_server(conftest.full_config())


async def test_render_snapshot_edit_mode_produces_real_image(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("render_snapshot", {"project": BLACKSITE, "mode": "edit"})
        assert result.is_error is not True
        data = result.structured_content
        assert data["pixel_renderer_success"] is True
        assert data["failures"] == []
        assert data["render_item_count"] > 0

        image = next(c for c in result.content if isinstance(c, ImageContent))
        assert image.mime_type == "image/png"
        assert len(image.data) > 0

        artifact_path = data["artifact_path"]
        assert artifact_path is not None
        written = Path(artifact_path).read_bytes()
        assert hashlib.sha256(written).hexdigest() == data["sha256"]


async def test_render_snapshot_runtime_mode_matches_edit_mode_for_same_viewport(server) -> None:
    """Both modes were shown (live) to produce byte-identical PNGs when given
    the same viewport, because OrthographicCamera construction only depends
    on the viewport aspect + scene.camera -- not on which code path built
    it. That's a real, checkable invariant, not an assumption.
    """
    async with Client(server) as client:
        edit_result = await client.call_tool("render_snapshot", {"project": BLACKSITE, "mode": "edit"})
        runtime_result = await client.call_tool("render_snapshot", {"project": BLACKSITE, "mode": "runtime"})
        assert edit_result.structured_content["sha256"] == runtime_result.structured_content["sha256"]


async def test_render_snapshot_compare_to_run_id_detects_identical_images(server) -> None:
    async with Client(server) as client:
        baseline = await client.call_tool("render_snapshot", {"project": BLACKSITE, "mode": "edit"})
        run_id = baseline.structured_content["run_id"]

        candidate = await client.call_tool(
            "render_snapshot", {"project": BLACKSITE, "mode": "edit", "compare_to_run_id": run_id}
        )
        assert candidate.is_error is not True
        comparison = candidate.structured_content["comparison"]
        assert comparison["same_dimensions"] is True
        assert comparison["different_pixel_count"] == 0
        assert comparison["difference_ratio"] == 0.0


async def test_render_snapshot_compare_to_unknown_run_id_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "render_snapshot",
            {"project": BLACKSITE, "mode": "edit", "compare_to_run_id": "not-a-real-run-id"},
        )
        assert result.is_error is True


async def test_render_snapshot_unknown_mode_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("render_snapshot", {"project": BLACKSITE, "mode": "not-a-mode"})
        assert result.is_error is True


async def test_render_snapshot_and_diagnostics_analyze_catch_real_space_pong_bug(server) -> None:
    """Space Pong's paddles use PrimitiveComponent(kind="rounded_rectangle"),
    which the real PygameRenderer does not support -- this is a genuine bug
    in the example project's data, not a synthetic fixture. Confirms the
    whole capture -> aggregate pipeline on real failure data.
    """
    async with Client(server) as client:
        snapshot = await client.call_tool("render_snapshot", {"project": SPACE_PONG, "mode": "runtime"})
        assert snapshot.is_error is not True
        data = snapshot.structured_content
        assert data["pixel_renderer_success"] is False
        assert data["diagnostic_count"] >= 2
        assert any("rounded_rectangle" in f for f in data["failures"])
        # Even on a failed frame, the surface still holds partially-correct
        # pixels -- an image must still come back, not nothing.
        assert any(isinstance(c, ImageContent) for c in snapshot.content)

        run_id = data["run_id"]
        analysis = await client.call_tool("diagnostics_analyze", {"run_id": run_id})
        assert analysis.is_error is not True
        result = analysis.structured_content
        assert result["raw_record_count"] >= 2
        assert result["unique_failures"] == 1  # both paddles collapse into one signature
        failure = result["failures"][0]
        assert failure["count"] >= 2
        assert "rounded_rectangle" in failure["message_template"] or "rounded_rectangle" in failure["sample"]


async def test_diagnostics_analyze_unknown_run_id_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("diagnostics_analyze", {"run_id": "not-a-real-run-id"})
        assert result.is_error is True


async def test_compare_modes_with_default_viewports_shows_no_difference_and_says_so(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "render_inspect", {"action": "compare_modes", "project": BLACKSITE}
        )
        assert result.is_error is not True
        assert result.structured_content["data"]["differences"] == []
        assert result.structured_content["note"] is not None
        assert "NOT informative" in result.structured_content["note"]


async def test_compare_modes_with_real_blacksite_dimensions_reproduces_real_height(server) -> None:
    """examples/blacksite_relay/__main__.py hardcodes
    OrthographicCamera(width=88.0, height=49.5) for a real 1280x720 game
    window (confirmed by direct source read). Feeding those exact numbers in
    as runtime_viewport must reproduce that exact height mathematically --
    this is the tool proving out against a known-real value, not a fixture.
    """
    async with Client(server) as client:
        result = await client.call_tool(
            "render_inspect",
            {
                "action": "compare_modes",
                "project": BLACKSITE,
                "edit_viewport_width": 320,
                "edit_viewport_height": 240,
                "runtime_viewport_width": 1280,
                "runtime_viewport_height": 720,
            },
        )
        assert result.is_error is not True
        data = result.structured_content["data"]
        assert data["runtime"]["camera"]["height"] == pytest.approx(49.5)
        assert data["runtime"]["camera"]["width"] == pytest.approx(88.0)
        differences = {d["field"]: d for d in data["differences"]}
        assert "height" in differences
        assert differences["height"]["classification"] == "EXPECTED_EDITOR_DIFFERENCE"
        # width/position/rotation are applied identically by both paths from
        # scene.camera -- they must NOT appear as differences here.
        assert "width" not in differences
        assert "position" not in differences


async def test_compare_modes_requires_project(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("render_inspect", {"action": "compare_modes"})
        assert result.is_error is True
