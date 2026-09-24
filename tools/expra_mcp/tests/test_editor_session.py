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
            assert snapshot.structured_content["data"]["available"] is True
            assert snapshot.structured_content["data"]["pixel_layer_active"] is True
            assert snapshot.structured_content["data"]["fallback_active"] is False
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


async def test_space_pong_paddles_use_canonical_pixel_path_across_play_stop_cycles(server) -> None:
    """Space Pong's rounded_rectangle paddles previously fell back to Canvas
    (frame_textures_available rejected the primitive). This proves, through
    the real MCP protocol against a real Tk editor, that the pixel path is
    now genuinely active in Edit AND stays active across repeated Play/Stop
    cycles -- not just that a static check passes once.
    """
    async with Client(server) as client:
        session_id = await _start_session(client)
        try:
            opened = await client.call_tool(
                "editor_session",
                {"action": "open_project", "session_id": session_id, "project": "examples/space_pong"},
            )
            assert opened.is_error is not True

            for _ in range(3):
                edit_snapshot = await client.call_tool(
                    "editor_session", {"action": "capture_viewport", "session_id": session_id}
                )
                assert edit_snapshot.is_error is not True
                assert edit_snapshot.structured_content["data"]["available"] is True
                assert edit_snapshot.structured_content["data"]["pixel_layer_active"] is True
                assert edit_snapshot.structured_content["data"]["fallback_active"] is False

                played = await client.call_tool(
                    "editor_session", {"action": "play", "session_id": session_id}
                )
                assert played.structured_content["data"]["run_state"] == "play"
                await client.call_tool(
                    "editor_session", {"action": "wait", "session_id": session_id, "duration_ms": 100}
                )

                play_snapshot = await client.call_tool(
                    "editor_session", {"action": "capture_viewport", "session_id": session_id}
                )
                assert play_snapshot.is_error is not True
                assert play_snapshot.structured_content["data"]["available"] is True
                assert play_snapshot.structured_content["data"]["pixel_layer_active"] is True
                assert play_snapshot.structured_content["data"]["fallback_active"] is False

                stopped = await client.call_tool(
                    "editor_session", {"action": "stop", "session_id": session_id}
                )
                assert stopped.structured_content["data"]["run_state"] == "edit"
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


async def test_observability_snapshot_reflects_a_real_blacksite_play_session(server) -> None:
    """Dogfoods the whole observability wiring pass through the real MCP
    protocol against a real Tk EditorWindow: open Blacksite -> Play ->
    genuine key-driven movement (input -> behaviour -> physics.overlap) ->
    Pause -> Resume -> Stop -> one shared snapshot should show app/ui/
    runtime/render/editor surfaces together, not fragments from separate
    watchers.
    """
    async with Client(server) as client:
        session_id = await _start_session(client)
        try:
            await client.call_tool(
                "editor_session", {"action": "open_project", "session_id": session_id, "project": BLACKSITE}
            )

            reset = await client.call_tool(
                "editor_session",
                {"action": "observability_snapshot", "session_id": session_id, "reset_observations": True},
            )
            assert reset.is_error is not True
            assert reset.structured_content["data"]["metrics"] == []

            await client.call_tool("editor_session", {"action": "play", "session_id": session_id})
            await client.call_tool(
                "editor_session", {"action": "send_key", "session_id": session_id, "key": "w", "phase": "down"}
            )
            await client.call_tool(
                "editor_session", {"action": "wait", "session_id": session_id, "duration_ms": 300}
            )
            await client.call_tool(
                "editor_session", {"action": "send_key", "session_id": session_id, "key": "w", "phase": "up"}
            )
            await client.call_tool("editor_session", {"action": "pause", "session_id": session_id})
            await client.call_tool("editor_session", {"action": "resume", "session_id": session_id})
            await client.call_tool(
                "editor_session", {"action": "wait", "session_id": session_id, "duration_ms": 100}
            )
            await client.call_tool("editor_session", {"action": "stop", "session_id": session_id})

            full = await client.call_tool(
                "editor_session", {"action": "observability_snapshot", "session_id": session_id}
            )
            assert full.is_error is not True
            targets = {m["target"] for m in full.structured_content["data"]["metrics"]}

            # One shared watcher end-to-end -- app/ui/runtime/render/editor
            # surfaces from a single real Play session, all in one snapshot.
            for expected in (
                "runtime:tick",
                "runtime:behaviour:update",
                "runtime:input:dispatch",
                "runtime:physics:query",
                "render:extract",
                "render:plan",
                "editor:preview:tick",
                "editor.pixelbridge.total",
            ):
                assert expected in targets, f"{expected} missing from {sorted(targets)}"

            runtime_only = await client.call_tool(
                "editor_session",
                {"action": "observability_snapshot", "session_id": session_id, "prefix": "runtime:"},
            )
            runtime_targets = {m["target"] for m in runtime_only.structured_content["data"]["metrics"]}
            assert runtime_targets  # non-empty
            assert all(t.startswith("runtime:") for t in runtime_targets)
            assert "editor.pixelbridge.total" not in runtime_targets
        finally:
            await client.call_tool("editor_session", {"action": "close", "session_id": session_id})
