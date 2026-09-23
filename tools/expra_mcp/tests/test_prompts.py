"""Protocol-level tests for the four MCP prompts, driven through the
official mcp Client's prompts/list and prompts/get -- real MCP primitives,
not a custom "prompt tool" workaround.
"""

from __future__ import annotations

import conftest
from expra_dev_mcp.server import build_server
from mcp import Client
from mcp.types import GetPromptResult, TextContent

EXPECTED_PROMPTS = {"debug-renderer", "mine-reference", "tk-regression", "release-check"}


def _first_message_text(result: GetPromptResult) -> str:
    content = result.messages[0].content
    assert isinstance(content, TextContent)
    return content.text


async def test_prompts_list_returns_all_four() -> None:
    server = build_server(conftest.full_config())
    async with Client(server) as client:
        result = await client.list_prompts()
        assert {p.name for p in result.prompts} == EXPECTED_PROMPTS


async def test_debug_renderer_prompt_mentions_real_tool_names() -> None:
    server = build_server(conftest.full_config())
    async with Client(server) as client:
        result = await client.get_prompt(
            "debug-renderer", {"project": "examples/blacksite_relay", "entity": "Aim Indicator"}
        )
        text = _first_message_text(result)
        assert "Aim Indicator" in text
        assert "workspace_doctor" in text
        assert "render_snapshot" in text
        assert "diagnostics_analyze" in text


async def test_mine_reference_prompt_references_source_tools() -> None:
    server = build_server(conftest.full_config())
    async with Client(server) as client:
        result = await client.get_prompt(
            "mine-reference", {"concept": "rotated sprite rendering", "references": "godot"}
        )
        text = _first_message_text(result)
        assert "source_search" in text
        assert "source_read" in text
        assert "godot" in text


async def test_tk_regression_prompt_mentions_exp_ui_and_coordinators() -> None:
    server = build_server(conftest.full_config())
    async with Client(server) as client:
        result = await client.get_prompt("tk-regression", {"symptom": "viewport freezes after Stop"})
        text = _first_message_text(result)
        assert "exp_ui" in text
        assert "UICoordinator" in text
        assert "editor_session" in text


async def test_release_check_prompt_mentions_run_checks_and_export() -> None:
    server = build_server(conftest.full_config())
    async with Client(server) as client:
        result = await client.get_prompt("release-check", {"project": "examples/blacksite_relay"})
        text = _first_message_text(result)
        assert "run_checks" in text
        assert "export_inspect" in text
        assert "allow_network" in text
