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


async def test_document_load_reports_generic_production_stages(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "performance_probe",
            {
                "action": "document_load",
                "project": BLACKSITE,
                "resource": "levels/main.level.pb",
                "iterations": 3,
            },
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["format"] == "protobuf"
        assert data["kind"] == "level"
        assert data["bytes"] > 0
        assert data["entities"] > 0
        assert data["stages"]["document:read"]["count"] == 3
        assert data["stages"]["document:decode"]["count"] == 3
        assert data["stages"]["document:convert"]["count"] == 3
        assert data["stages"]["document:construct"]["count"] == 3
        for target in (
            "document:construct:entities",
            "document:construct:components",
            "document:construct:hierarchy",
        ):
            assert data["stages"][target]["count"] == 3
        assert data["stages"]["scene:resolve_instances"]["count"] == 3
        assert data["stages"]["document:load"]["count"] == 3
        assert data["first_load_total_ms"] >= 0


async def test_document_load_compares_equivalent_json_and_protobuf(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "performance_probe",
            {
                "action": "document_load",
                "project": BLACKSITE,
                "resource": "scenes/main.json",
                "compare_resource": "levels/main.level.pb",
                "iterations": 2,
            },
        )
        assert result.is_error is not True
        comparisons = result.structured_content["comparisons"]
        assert [item["format"] for item in comparisons] == ["legacy_json", "protobuf"]
        # Legacy flat JSON has no kind field; the PB resource is explicitly
        # typed. The probe reports the kind actually exercised rather than
        # inferring one from the comparison pair.
        assert [item["kind"] for item in comparisons] == ["scene", "level"]
        assert all("document:load" in item["stages"] for item in comparisons)


async def test_document_load_supports_deterministic_synthetic_documents(server) -> None:
    async with Client(server) as client:
        request = {
            "action": "document_load",
            "synthetic_entity_count": 100,
            "synthetic_kind": "scene",
            "synthetic_component_density": 0.5,
            "iterations": 2,
        }
        result = await client.call_tool("performance_probe", request)
        repeat = await client.call_tool("performance_probe", request)
        assert result.is_error is not True
        assert repeat.is_error is not True
        data = result.structured_content
        repeated_data = repeat.structured_content
        assert data["sha256"] == repeated_data["sha256"]
        assert data["bytes"] == repeated_data["bytes"]
        assert data["entities"] == repeated_data["entities"]
        assert data["components"] == repeated_data["components"]
        assert data["format"] == "protobuf"
        assert data["kind"] == "scene"
        assert data["entities"] >= 100
        assert data["components"] >= data["entities"]


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
