"""Protocol-level tests for editor_session, driven through the official mcp
Client against a REAL Tk EditorWindow worker process on this machine's real
DISPLAY. Each test that opens a session is responsible for closing it --
these tests spin up genuine editor processes, so they're heavier than the
rest of the suite; kept to a reasonable count with related assertions
grouped into single sessions rather than one editor per assertion.
"""

from __future__ import annotations

import conftest
import pytest
from expra_dev_mcp.server import build_server
from mcp import Client
from mcp.types import ImageContent

BLACKSITE = "examples/blacksite_relay"


@pytest.fixture
def server():
    return build_server(conftest.full_config())


async def _start_session(client: Client) -> str:
    result = await client.call_tool("editor_session", {"action": "start"})
    assert result.is_error is not True
    data = result.structured_content
    assert data["editor_session_available"] is True
    return data["session_id"]


async def test_start_and_close_lifecycle(server) -> None:
    async with Client(server) as client:
        session_id = await _start_session(client)
        result = await client.call_tool("editor_session", {"action": "close", "session_id": session_id})
        assert result.is_error is not True
        assert result.structured_content["data"]["closed"] is True


async def test_unknown_session_id_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "editor_session", {"action": "state", "session_id": "not-a-real-session"}
        )
        assert result.is_error is True


async def test_action_without_session_id_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("editor_session", {"action": "state"})
        assert result.is_error is True


async def test_open_project_rejects_untrusted_project(server) -> None:
    async with Client(server) as client:
        session_id = await _start_session(client)
        try:
            result = await client.call_tool(
                "editor_session",
                {"action": "open_project", "session_id": session_id, "project": "src/expra_engine"},
            )
            assert result.is_error is True
        finally:
            await client.call_tool("editor_session", {"action": "close", "session_id": session_id})


async def test_full_spec_acceptance_workflow(server) -> None:
    """start -> open Blacksite -> capture -> Play -> press W -> wait ->
    inspect -> capture -> select -> Stop (edit scene restored) -> close --
    the exact spec acceptance scenario, executed against the real editor.
    """
    async with Client(server) as client:
        session_id = await _start_session(client)
        try:
            opened = await client.call_tool(
                "editor_session", {"action": "open_project", "session_id": session_id, "project": BLACKSITE}
            )
            assert opened.is_error is not True
            assert opened.structured_content["data"]["executed_project_code"] is True
            assert opened.structured_content["data"]["entity_count"] == 66

            baseline = await client.call_tool(
                "editor_session", {"action": "inspect", "session_id": session_id, "entity": "Operative"}
            )
            baseline_y = baseline.structured_content["data"]["world_pose"]["y"]

            played = await client.call_tool("editor_session", {"action": "play", "session_id": session_id})
            assert played.structured_content["data"]["run_state"] == "play"

            await client.call_tool(
                "editor_session", {"action": "send_key", "session_id": session_id, "key": "w", "phase": "down"}
            )
            await client.call_tool(
                "editor_session", {"action": "wait", "session_id": session_id, "duration_ms": 400}
            )
            await client.call_tool(
                "editor_session", {"action": "send_key", "session_id": session_id, "key": "w", "phase": "up"}
            )

            moved = await client.call_tool(
                "editor_session", {"action": "inspect", "session_id": session_id, "entity": "Operative"}
            )
            moved_y = moved.structured_content["data"]["world_pose"]["y"]
            assert moved_y != baseline_y  # real Behaviour-driven movement, via genuine Tk key events

            snapshot = await client.call_tool(
                "editor_session", {"action": "capture_viewport", "session_id": session_id}
            )
            assert snapshot.is_error is not True
            image = next((c for c in snapshot.content if isinstance(c, ImageContent)), None)
            assert image is not None
            assert image.mime_type == "image/png"

            selected = await client.call_tool(
                "editor_session", {"action": "select_entity", "session_id": session_id, "entity": "Operative"}
            )
            assert selected.structured_content["data"]["selected_id"] is not None
            assert selected.structured_content["data"]["selected_id"] != "Operative"  # resolved to a real entity_id

            stopped = await client.call_tool("editor_session", {"action": "stop", "session_id": session_id})
            assert stopped.structured_content["data"]["run_state"] == "edit"

            restored = await client.call_tool(
                "editor_session", {"action": "inspect", "session_id": session_id, "entity": "Operative"}
            )
            assert restored.structured_content["data"]["world_pose"]["y"] == baseline_y  # edit scene restored
        finally:
            await client.call_tool("editor_session", {"action": "close", "session_id": session_id})


async def test_send_key_requires_key(server) -> None:
    async with Client(server) as client:
        session_id = await _start_session(client)
        try:
            result = await client.call_tool("editor_session", {"action": "send_key", "session_id": session_id})
            assert result.is_error is True
        finally:
            await client.call_tool("editor_session", {"action": "close", "session_id": session_id})


async def test_frame_scene_reports_unavailable_honestly(server) -> None:
    async with Client(server) as client:
        session_id = await _start_session(client)
        try:
            result = await client.call_tool(
                "editor_session", {"action": "frame_scene", "session_id": session_id}
            )
            assert result.is_error is not True
            assert result.structured_content["data"]["available"] is False
        finally:
            await client.call_tool("editor_session", {"action": "close", "session_id": session_id})
