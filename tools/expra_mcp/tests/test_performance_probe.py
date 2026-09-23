"""Protocol-level tests for performance_probe, driven through the official
mcp Client. render_stress/resource_cache exercise the static subprocess
path against real Blacksite Relay assets; editor_redraw_stress exercises a
real live Tk editor session (heavier -- kept to a single test).
"""

from __future__ import annotations

import conftest
import pytest
from expra_dev_mcp.server import build_server
from mcp import Client

BLACKSITE = "examples/blacksite_relay"


@pytest.fixture
def server():
    return build_server(conftest.full_config())


async def test_render_stress_reports_bounded_cache(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "performance_probe",
            {"action": "render_stress", "project": BLACKSITE, "iterations": 20, "track_memory": True},
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["verdict"] == "bounded"
        assert data["resource_cache_count_after"] >= data["resource_cache_count_before"]
        # Symmetric handler measurement: our own capture handler must not
        # appear in either count (regression guard for the exact bug found
        # live during implementation).
        assert data["logger_handler_count_before"] == data["logger_handler_count_after"]
        assert data["memory_delta_kb"] is not None
        assert data["iterations"] == 20


async def test_render_stress_requires_project(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("performance_probe", {"action": "render_stress"})
        assert result.is_error is True


async def test_resource_cache_reports_bounded(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "performance_probe",
            {
                "action": "resource_cache",
                "project": BLACKSITE,
                "asset_ids": ["assets://kenney/player_survivor_gun.png", "assets://kenney/zombie.png"],
                "iterations": 15,
            },
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["verdict"] == "bounded"
        assert data["asset_count"] == 2
        assert data["resource_cache_count_after"] <= 3


async def test_resource_cache_requires_asset_ids(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "performance_probe", {"action": "resource_cache", "project": BLACKSITE}
        )
        assert result.is_error is True


async def test_editor_redraw_stress_requires_session_id(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("performance_probe", {"action": "editor_redraw_stress"})
        assert result.is_error is True


async def test_editor_redraw_stress_reports_bounded_canvas_state(server) -> None:
    async with Client(server) as client:
        start_result = await client.call_tool("editor_session", {"action": "start"})
        session_id = start_result.structured_content["session_id"]
        try:
            await client.call_tool(
                "editor_session", {"action": "open_project", "session_id": session_id, "project": BLACKSITE}
            )
            result = await client.call_tool(
                "performance_probe",
                {"action": "editor_redraw_stress", "session_id": session_id, "iterations": 15},
            )
            assert result.is_error is not True
            data = result.structured_content
            assert data["verdict"] == "bounded"
            assert data["canvas_item_count_before"] == data["canvas_item_count_after"]
            assert data["photoimage_count_before"] == data["photoimage_count_after"]
            assert data["logger_handler_count_before"] == data["logger_handler_count_after"]
        finally:
            await client.call_tool("editor_session", {"action": "close", "session_id": session_id})
