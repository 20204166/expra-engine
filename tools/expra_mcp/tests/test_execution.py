"""Protocol-level tests for runtime_probe / run_checks / export_inspect,
driven through the official mcp Client. runtime_probe tests assert on real
Behaviour-driven entity movement (not a fixture -- the real
blacksite_relay_behaviour.py actually moves the "Operative" entity in
response to simulated input, dispatched through the real Engine event
queue). run_checks tests run real pytest/ruff/diff against this actual
repo. export_inspect avoids ever triggering a real network-touching export
in the test suite -- only 'plan' and the allow_network=false refusal path
are exercised for 'export', plus 'verify' against a hand-built minimal
build directory.
"""

from __future__ import annotations

import json

import conftest
import pytest
from expra_dev_mcp.server import build_server
from mcp import Client

BLACKSITE = "examples/blacksite_relay"


@pytest.fixture
def server():
    return build_server(conftest.full_config())


# ---------------------------------------------------------------------------
# runtime_probe
# ---------------------------------------------------------------------------


async def test_runtime_probe_rejects_untrusted_project(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "runtime_probe", {"project": "src/expra_engine", "steps": [{"action": "play"}]}
        )
        assert result.is_error is True


async def test_runtime_probe_real_behaviour_moves_entity(server) -> None:
    """Real acceptance-style sequence: play, press a key, tick, inspect --
    exactly the spec's "press W -> wait -> inspect" workflow, minus the
    editor GUI (that's Phase 2F). Asserts the entity ACTUALLY MOVED, proving
    the real Behaviour script ran, not just that steps returned ok=True.
    """
    async with Client(server) as client:
        before = await client.call_tool(
            "runtime_probe",
            {"project": BLACKSITE, "steps": [{"action": "play"}, {"action": "inspect_entity", "entity": "Operative"}]},
        )
        assert before.is_error is not True
        before_pose = before.structured_content["steps"][1]["data"]["world_pose"]

        moved = await client.call_tool(
            "runtime_probe",
            {
                "project": BLACKSITE,
                "steps": [
                    {"action": "play"},
                    {"action": "key_down", "key": "w"},
                    {"action": "tick", "dt": 0.25},
                    {"action": "key_up", "key": "w"},
                    {"action": "inspect_entity", "entity": "Operative"},
                    {"action": "stop"},
                ],
            },
        )
        assert moved.is_error is not True
        data = moved.structured_content
        assert all(s["ok"] for s in data["steps"])
        assert data["executed_project_code"] is True

        key_down_events = data["steps"][1]["data"]["action_events"]
        assert key_down_events == [{"action": "move_up", "phase": "pressed"}]

        after_pose = data["steps"][4]["data"]["world_pose"]
        assert after_pose["y"] != before_pose["y"]  # real Behaviour-driven movement


async def test_runtime_probe_render_step_matches_entity(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "runtime_probe",
            {
                "project": BLACKSITE,
                "steps": [{"action": "play"}, {"action": "inspect_render", "entity": "Aim Indicator"}],
            },
        )
        data = result.structured_content["steps"][1]["data"]
        assert len(data["render_items"]) == 1
        assert data["render_items"][0]["key"] == data["entity"]["entity_id"]


async def test_runtime_probe_unknown_step_does_not_abort_sequence(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "runtime_probe",
            {
                "project": BLACKSITE,
                "steps": [
                    {"action": "play"},
                    {"action": "not_a_real_action"},
                    {"action": "inspect_entity", "entity": "Operative"},
                ],
            },
        )
        assert result.is_error is not True
        steps = result.structured_content["steps"]
        assert steps[1]["ok"] is False
        assert steps[1]["error"] is not None
        assert steps[2]["ok"] is True  # sequence continued past the bad step


async def test_runtime_probe_overlap_query(server) -> None:
    async with Client(server) as client:
        entity = await client.call_tool(
            "runtime_probe",
            {"project": BLACKSITE, "steps": [{"action": "play"}, {"action": "inspect_entity", "entity": "Operative"}]},
        )
        entity_id = entity.structured_content["steps"][1]["data"]["entity"]["entity_id"]

        result = await client.call_tool(
            "runtime_probe",
            {"project": BLACKSITE, "steps": [{"action": "play"}, {"action": "overlap", "entity": entity_id}]},
        )
        assert result.is_error is not True
        assert result.structured_content["steps"][1]["ok"] is True
        assert "overlapping" in result.structured_content["steps"][1]["data"]


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------


async def test_run_checks_blacksite_profile_passes(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("run_checks", {"profile": "blacksite"})
        assert result.is_error is not True
        data = result.structured_content
        assert data["success"] is True
        assert data["tests_collected"] == data["passed"]
        assert data["failed"] == 0
        assert data["log_path"] is not None


async def test_run_checks_diff_check(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("run_checks", {"profile": "diff_check"})
        assert result.is_error is not True
        assert result.structured_content["exit_code"] is not None


async def test_run_checks_focused_requires_test_target(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("run_checks", {"profile": "focused"})
        assert result.is_error is True


async def test_run_checks_focused_rejects_path_escape(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "run_checks", {"profile": "focused", "test_target": "../tools/expra_mcp/tests/test_decoupling.py"}
        )
        assert result.is_error is True


async def test_run_checks_unknown_profile_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("run_checks", {"profile": "not-a-real-profile"})
        assert result.is_error is True


# ---------------------------------------------------------------------------
# export_inspect
# ---------------------------------------------------------------------------


async def test_export_inspect_plan_is_valid_for_real_project(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "export_inspect",
            {"action": "plan", "project": BLACKSITE, "output_dir": "/tmp/expra-mcp-test-export"},
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["plan_valid"] is True
        assert data["plan"]["game_name"] == "Blacksite Relay"
        assert data["plan"]["target"] == "linux"


async def test_export_inspect_plan_rejects_untrusted_project(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "export_inspect",
            {"action": "plan", "project": "src/expra_engine", "output_dir": "/tmp/expra-mcp-test-export"},
        )
        assert result.is_error is True


async def test_export_inspect_export_refused_without_allow_network(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "export_inspect",
            {"action": "export", "project": BLACKSITE, "output_dir": "/tmp/expra-mcp-test-export"},
        )
        assert result.is_error is not True
        data = result.structured_content
        assert data["success"] is False
        assert "allow_network" in data["error"]


async def test_export_inspect_verify_against_hand_built_manifest(server, tmp_path) -> None:
    """Doesn't run a real (network-touching) export -- builds the minimal
    real file shape verify_export() checks for (build_manifest.json +
    asset_manifest.json with the real required keys) and confirms the tool
    calls the REAL verify_export()/forbidden-import scan against it.
    """
    build_dir = tmp_path / "fake_build"
    build_dir.mkdir()
    (build_dir / "build_manifest.json").write_text(
        json.dumps(
            {
                "game_name": "Test",
                "game_version": "1.0.0",
                "engine_version": "0.0.0",
                "target": "linux",
                "python_version": "3.12.4",
                "arch": "amd64",
                "compile_bytecode": True,
                "entry_point": "__main__.py",
                "build_timestamp": "2026-01-01T00:00:00+00:00",
                "runtime_profile": "none",
            }
        )
    )
    (build_dir / "asset_manifest.json").write_text(json.dumps({"entries": []}))

    async with Client(server) as client:
        result = await client.call_tool("export_inspect", {"action": "verify", "build_dir": str(build_dir)})
        assert result.is_error is not True
        data = result.structured_content
        assert data["verification"]["success"] is True
        assert data["forbidden_imports"] == []
        assert data["build_manifest"]["game_name"] == "Test"


async def test_export_inspect_verify_missing_dir_is_error(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("export_inspect", {"action": "verify", "build_dir": "/tmp/no-such-build-dir"})
        assert result.is_error is True
