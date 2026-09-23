"""Protocol-level tests for source_search / source_read / repo_inspect /
source://{repo}/{path}, driven through the official mcp Client against real
repo content (expra-engine itself plus the five real reference checkouts on
this machine). These exercise the pure-Python search fallback specifically,
since `rg` is not on this machine's PATH (see workspace_doctor's tools[]).
"""

from __future__ import annotations

import shutil

import conftest
import pytest
from expra_dev_mcp.server import build_server
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import TextResourceContents

REPO_ROOT = conftest.REPO_ROOT


@pytest.fixture
def server():
    return build_server(conftest.full_config())


def test_rg_is_not_on_path_on_this_machine() -> None:
    """Ground the rest of this file's claims: prove the environment
    assumption that makes the pure-Python fallback load-bearing here.
    """
    assert shutil.which("rg") is None


async def test_source_search_literal_finds_real_expra_symbol(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "source_search",
            {"repos": ["expra"], "query": "class Entity", "mode": "literal", "max_results": 10},
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["backend"] == "pure_python"
        assert data["matches"], "expected at least one match for 'class Entity' in expra"
        assert any(m["relative_path"].endswith("entity.py") for m in data["matches"])


async def test_source_search_finds_real_godot_sprite2d(server) -> None:
    if "godot" not in conftest.full_config().references:
        pytest.skip("godot-master reference not present on this machine")
    async with Client(server) as client:
        result = await client.call_tool(
            "source_search",
            {"repos": ["godot"], "query": "class Sprite2D", "mode": "literal", "max_results": 10},
        )
        assert result.is_error is not True
        data = result.structured_content
        assert any("sprite_2d" in m["relative_path"] for m in data["matches"])


async def test_source_search_unknown_repo_is_an_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "source_search", {"repos": ["not-a-repo"], "query": "x", "max_results": 5}
        )
        assert result.is_error is True


async def test_source_search_respects_max_results_and_reports_truncated(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "source_search",
            {"repos": ["expra"], "query": "def ", "mode": "literal", "max_results": 3, "context_lines": 0},
        )
        data = result.structured_content
        assert len(data["matches"]) <= 3
        if len(data["matches"]) == 3:
            assert data["truncated"] is True


async def test_source_read_returns_real_pyproject_content(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "source_read", {"repo": "expra", "relative_path": "pyproject.toml"}
        )
        assert result.is_error is not True
        data = result.structured_content
        assert "expra-engine" in data["content"]
        assert data["total_lines"] > 0
        assert data["revision"] is not None  # expra IS a git checkout


async def test_source_read_path_escape_is_rejected(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "source_read", {"repo": "expra", "relative_path": "../../../../etc/passwd"}
        )
        assert result.is_error is True


async def test_source_read_reference_repo_has_null_revision_when_not_a_git_checkout(server) -> None:
    if "godot" not in conftest.full_config().references:
        pytest.skip("godot-master reference not present on this machine")
    async with Client(server) as client:
        result = await client.call_tool(
            "source_read", {"repo": "godot", "relative_path": "COPYRIGHT.txt", "start_line": 1, "end_line": 5}
        )
        assert result.is_error is not True
        data = result.structured_content
        # confirmed by recon: none of the reference repos are git checkouts here
        assert data["revision"] is None


async def test_repo_inspect_status_and_head_are_real(server) -> None:
    async with Client(server) as client:
        head_result = await client.call_tool("repo_inspect", {"action": "head"})
        assert head_result.is_error is not True
        head = head_result.structured_content["head_commit"]
        assert head and len(head) == 40  # real git SHA-1

        status_result = await client.call_tool("repo_inspect", {"action": "status"})
        assert status_result.is_error is not True
        assert status_result.structured_content["branch"] == "main"


async def test_resource_reads_real_expra_file(server) -> None:
    async with Client(server) as client:
        result = await client.read_resource("source://expra/pyproject.toml")
        content = result.contents[0]
        assert isinstance(content, TextResourceContents)
        assert "expra-engine" in content.text


async def test_resource_rejects_path_escape(server) -> None:
    async with Client(server) as client:
        with pytest.raises(MCPError):
            await client.read_resource("source://expra/../../../../etc/passwd")
