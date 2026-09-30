"""The MCP editor worker drives the real Qt editor over its JSON line protocol.

Launches ``_editor_worker.py`` as a subprocess (the way the expra-mcp server does) and
speaks its JSON line protocol: MCP goes through the shared editor state/commands and the
Qt event system, never through widgets directly.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.project import Project
from expra_engine.core.scene import Level, Scene
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.runtime.visual_components import PrimitiveComponent

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tools" / "expra_mcp" / "src" / "expra_dev_mcp" / "_editor_worker.py"

pytestmark = pytest.mark.skipif(not WORKER.is_file(), reason="MCP worker not present")


class Worker:
    def __init__(self, tmp_path: Path) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        env["QT_QPA_PLATFORM"] = "offscreen"  # headless Qt session
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        self.process = subprocess.Popen(
            [sys.executable, str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self._next_id = 1
        self._lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        self.handshake = self._read()

    def _pump_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line)
        self._lines.put("")

    def _read(self, timeout: float = 30.0) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.process.kill()
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise AssertionError(
                f"worker gave no response to {getattr(self, 'last_command', 'handshake')!r} in {timeout}s; stderr:\n{stderr}"
            ) from None
        assert line, "worker exited early"
        return json.loads(line)

    def call(self, command: str, **params: Any) -> dict[str, Any]:
        self.last_command = command
        assert self.process.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        self.process.stdin.write(json.dumps({"id": request_id, "command": command, **params}) + "\n")
        self.process.stdin.flush()
        response = self._read()
        assert response["id"] == request_id
        return response

    def close(self) -> None:
        try:
            self.call("close")
        finally:
            self.process.wait(timeout=20)


def _project(root: Path) -> Project:
    project = Project.create("McpEditorWorker", root / "project")
    scene = Scene("Main")
    hero = scene.create_entity("Hero")
    hero.add_component(TransformComponent(x=1.0, y=2.0))
    hero.add_component(PrimitiveComponent())
    scene.create_entity("Crate").add_component(TransformComponent(x=-3.0, y=0.5))
    project.save_document(scene, "scenes/main.scene.pb")
    project.save()
    return project


def _session(tmp_path: Path) -> dict[str, Any]:
    project = _project(tmp_path)
    worker = Worker(tmp_path)
    out: dict[str, Any] = {"handshake_ok": worker.handshake["ok"]}
    try:
        assert worker.handshake["ok"], worker.handshake
        out["handshake_ui"] = worker.handshake["data"].get("ui")
        opened = worker.call(
            "open_project",
            expra_root=str(project.path.parent),
            project=project.path.name,
            scene="scenes/main.scene.pb",
        )
        assert opened["ok"], opened
        out["opened"] = dict(opened["data"])
        reopened = worker.call("open_scene", relative_path="scenes/main.scene.pb")
        assert reopened["ok"], reopened
        out["reopened_entities"] = reopened["data"]["entity_count"]
        entities = worker.call("inspect")["data"]["entity_names"]
        out["entities"] = sorted(entities)
        selected = worker.call("select_entity", entity="Hero")
        assert selected["ok"], selected
        out["selected_name"] = selected["data"]["entity_name"]
        out["state_selected"] = worker.call("state")["data"]["selected_id"] == selected["data"]["selected_id"]
        out["inspect_hero"] = worker.call("inspect", entity="Hero")["data"]
        out["frame_scene"] = worker.call("frame_scene")["data"]
        out["play"] = worker.call("play")["data"]
        out["wait"] = worker.call("wait", duration_ms=150)["data"]
        out["send_key_down"] = worker.call("send_key", key="d", phase="down")["data"]["key"]
        out["send_key_up"] = worker.call("send_key", key="d", phase="up")["data"]["key"]
        out["pause"] = worker.call("pause")["data"]
        out["stop"] = worker.call("stop")["data"]
        out["capture_keys"] = sorted(worker.call("capture_viewport")["data"])
        probe = worker.call("performance_probe", iterations=5)
        assert probe["ok"], probe
        out["probe_verdict"] = probe["data"]["verdict"]
        snapshot = worker.call("observability_snapshot")
        assert snapshot["ok"], snapshot
        out["observability_has_metrics"] = snapshot["data"]["metric_count"] > 0
        out["save"] = worker.call("save_scene")["ok"]
        unknown = worker.call("no_such_command")
        out["unknown_is_error"] = unknown["ok"] is False
    finally:
        worker.close()
    return out


def test_editor_worker_protocol_session(tmp_path) -> None:
    out = _session(tmp_path)
    assert out.pop("handshake_ui") == "qt"
    assert out["opened"]["project_name"] == "McpEditorWorker"
    assert out["opened"]["entity_count"] == 2
    assert out["reopened_entities"] == 2
    assert out["entities"] == ["Crate", "Hero"]
    assert out["selected_name"] == "Hero"
    assert out["state_selected"] is True
    assert out["inspect_hero"]["entity"]["name"] == "Hero"
    assert out["inspect_hero"]["world_pose"]["x"] == 1.0
    assert out["play"]["run_state"] == "play"
    assert out["wait"]["waited_ms"] == 150
    assert (out["send_key_down"], out["send_key_up"]) == ("d", "d")
    assert out["pause"]["run_state"] == "paused"
    assert out["stop"]["run_state"] == "edit"
    assert "available" in out["capture_keys"]
    assert out["probe_verdict"] in {"bounded", "growing", "inconclusive"}
    assert out["observability_has_metrics"] is True
    assert out["save"] is True
    assert out["unknown_is_error"] is True


def test_editor_worker_opens_a_world_entrypoint(tmp_path: Path) -> None:
    project = Project.create("WorldProject", tmp_path / "world-project")
    level = Level("Start")
    project.save_document(level, "levels/start.level.pb")
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("start", "levels/start.level.pb"),),
        initial_level_id="start",
    )
    project.save_document(world, "worlds/main.world.pb")
    project.set_entrypoint("worlds/main.world.pb")
    project.save()

    worker = Worker(tmp_path)
    try:
        opened = worker.call(
            "open_project",
            expra_root=str(project.path.parent),
            project=project.path.name,
        )
        assert opened["ok"], opened
        assert opened["data"]["document_kind"] == "world"
        assert opened["data"]["entity_count"] == 0
    finally:
        worker.close()
