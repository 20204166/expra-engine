"""Protocol-level tests for expra_inspect / render_inspect / resource_trace,
driven through the official mcp Client against the REAL Blacksite Relay
example project (examples/blacksite_relay) -- including its real "Aim
Indicator" entity, the exact one named in the spec's acceptance scenario.

These exercise the full subprocess bridge to the configured Expra
interpreter (_static_runner.py), not just in-process Python calls, so a
regression in the runner's stdout contract (e.g. pygame's import banner
corrupting the JSON response) would be caught here.
"""

from __future__ import annotations

import conftest
import pytest
from expra_dev_mcp.server import build_server
from mcp import Client
from mcp.types import ImageContent, TextContent

PROJECT = "examples/blacksite_relay"


@pytest.fixture
def server():
    return build_server(conftest.full_config())


# ---------------------------------------------------------------------------
# expra_inspect
# ---------------------------------------------------------------------------


async def test_expra_inspect_project(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("expra_inspect", {"action": "project", "project": PROJECT})
        assert result.is_error is not True
        data = result.structured_content
        assert data["executed_project_code"] is False
        assert data["data"]["project"]["name"] == "Blacksite Relay"
        assert "levels/main.level.pb" in data["data"]["project"]["level_paths"]


async def test_expra_inspect_scene_lists_real_entities(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("expra_inspect", {"action": "scene", "project": PROJECT})
        data = result.structured_content["data"]
        names = [e["name"] for e in data["scene"]["entities"]]
        assert "Aim Indicator" in names
        assert "Operative" in names
        assert data["entity_count"] == len(names)


async def test_expra_inspect_entity_aim_indicator(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "expra_inspect", {"action": "entity", "project": PROJECT, "entity": "Aim Indicator"}
        )
        assert result.is_error is not True
        data = result.structured_content["data"]
        assert data["entity"]["name"] == "Aim Indicator"
        component_types = [c["type"] for c in data["entity"]["components"]]
        assert "transform" in component_types
        assert "primitive" in component_types
        assert "world_pose" in data
        assert set(data["world_pose"]) == {"x", "y", "rotation"}


async def test_expra_inspect_component(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "expra_inspect",
            {"action": "component", "project": PROJECT, "entity": "Aim Indicator", "component_type": "primitive"},
        )
        assert result.is_error is not True
        component = result.structured_content["data"]["component"]
        assert component["type"] == "primitive"
        assert component["kind"] == "rectangle"


async def test_expra_inspect_component_schema(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "expra_inspect", {"action": "component_schema", "component_type": "primitive"}
        )
        assert result.is_error is not True
        spec = result.structured_content["data"]["spec"]
        field_names = {f["name"] for f in spec["fields"]}
        assert "kind" in field_names
        assert "outline_width" in field_names


async def test_expra_inspect_input_map_is_real_bindings(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("expra_inspect", {"action": "input_map", "project": PROJECT})
        data = result.structured_content["data"]
        assert data["bindings"]["move_up"] == "keyboard:w"
        assert result.structured_content["available_statically"] is True


async def test_expra_inspect_systems_unavailable_statically(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("expra_inspect", {"action": "systems"})
        assert result.structured_content["available_statically"] is False
        assert "runtime_probe" in result.structured_content["note"]


async def test_expra_inspect_lifecycle_unavailable_statically(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("expra_inspect", {"action": "lifecycle"})
        assert result.structured_content["available_statically"] is False


async def test_expra_inspect_missing_required_param_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("expra_inspect", {"action": "entity"})
        assert result.is_error is True


async def test_expra_inspect_unknown_entity_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "expra_inspect", {"action": "entity", "project": PROJECT, "entity": "Not A Real Entity"}
        )
        assert result.is_error is True


# ---------------------------------------------------------------------------
# render_inspect
# ---------------------------------------------------------------------------


async def test_render_inspect_capabilities_is_headless(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("render_inspect", {"action": "capabilities"})
        assert result.is_error is not True
        caps = result.structured_content["data"]["capabilities"]
        assert caps["headless"] is True
        assert caps["primitive"] is True


async def test_render_inspect_frame_has_real_items(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("render_inspect", {"action": "frame", "project": PROJECT})
        data = result.structured_content["data"]
        assert data["item_count"] > 0
        assert len(data["items"]) == data["item_count"]


async def test_render_inspect_plan_matches_blacksite_scale(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("render_inspect", {"action": "plan", "project": PROJECT})
        data = result.structured_content["data"]
        # 66 entities in the real scene -- the plan should have a comparable
        # number of operations, not a hardcoded/fake constant.
        assert data["operation_count"] > 30


async def test_render_inspect_operation_by_index(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "render_inspect", {"action": "operation", "project": PROJECT, "operation_index": 0}
        )
        assert result.is_error is not True
        assert result.structured_content["data"]["operation_index"] == 0


async def test_render_inspect_operation_out_of_range_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "render_inspect", {"action": "operation", "project": PROJECT, "operation_index": 999999}
        )
        assert result.is_error is True


async def test_render_inspect_entity_traces_aim_indicator_render_item(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "render_inspect", {"action": "entity", "project": PROJECT, "entity": "Aim Indicator"}
        )
        assert result.is_error is not True
        data = result.structured_content["data"]
        items = data["render_items"]
        assert len(items) == 1
        assert items[0]["key"] == data["entity"]["entity_id"]
        assert items[0]["primitive"]["kind"] == "rectangle"


async def test_render_inspect_cache_unavailable_statically(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("render_inspect", {"action": "cache", "project": PROJECT})
        assert result.structured_content["available_statically"] is False


# ---------------------------------------------------------------------------
# resource_trace
# ---------------------------------------------------------------------------


async def test_resource_trace_real_asset_decodes(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "resource_trace",
            {"project": PROJECT, "asset_id": "assets://kenney/player_survivor_gun.png"},
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["exists"] is True
        assert data["decode_status"] == "ok"
        assert data["pixel_width"] and data["pixel_height"]
        assert data["has_alpha"] is True
        assert data["content_hash"]


async def test_resource_trace_missing_asset(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "resource_trace",
            {"project": PROJECT, "asset_id": "assets://kenney/does_not_exist.png"},
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["exists"] is False
        assert data["decode_status"] == "not_attempted"


async def test_resource_trace_with_preview_returns_real_image_content(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "resource_trace",
            {"project": PROJECT, "asset_id": "assets://kenney/player_survivor_gun.png", "include_preview": True},
        )
        assert result.is_error is not True
        assert result.structured_content["decode_status"] == "ok"
        kinds = [type(c) for c in result.content]
        assert TextContent in kinds
        assert ImageContent in kinds
        image = next(c for c in result.content if isinstance(c, ImageContent))
        assert image.mime_type == "image/png"
        assert len(image.data) > 0
