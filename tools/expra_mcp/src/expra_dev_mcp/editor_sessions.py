"""EditorSessionManager: spawns and drives the long-lived Tk editor worker
subprocess (_editor_worker.py), one per session. Mutations to a given
session are serialized through an asyncio.Lock (spec: "one editor session
must serialize mutations to its own worker"). Never runs Tk in this
process -- every Tk call happens inside the worker's own main thread.

Headless fallback manages ``Xvfb`` directly rather than shelling out to
``xvfb-run``: that wrapper script runs the wrapped command as
``"$@" 2>&1`` (confirmed by reading /usr/bin/xvfb-run), merging the
worker's stderr into its stdout -- which would corrupt the newline-
delimited JSON protocol the moment expra_engine logs anything. Managing
our own ``Xvfb :N &`` process keeps stdout/stderr as genuinely separate
pipes, exactly like the native-display path.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import ExpraMcpConfig

_WORKER_PATH = Path(__file__).with_name("_editor_worker.py")


class EditorSessionError(RuntimeError):
    pass


def _find_free_display_num(start: int = 99) -> int:
    n = start
    while Path(f"/tmp/.X{n}-lock").exists():
        n += 1
    return n


class _EditorSession:
    def __init__(
        self,
        session_id: str,
        process: asyncio.subprocess.Process,
        *,
        xvfb_process: asyncio.subprocess.Process | None = None,
    ) -> None:
        self.session_id = session_id
        self.process = process
        self.xvfb_process = xvfb_process
        self.lock = asyncio.Lock()
        self.last_activity = time.monotonic()
        self.closed = False

    async def send(self, command: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        if self.closed or self.process.returncode is not None:
            raise EditorSessionError(f"session {self.session_id!r} is no longer running")
        assert self.process.stdin is not None
        assert self.process.stdout is not None

        request = {"id": int(time.time() * 1000) % 1_000_000, "command": command, **params}
        self.process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await self.process.stdin.drain()

        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=timeout)
        except TimeoutError as exc:
            raise EditorSessionError(f"session {self.session_id!r} timed out waiting for {command!r}") from exc
        if not line:
            raise EditorSessionError(f"session {self.session_id!r} worker closed its stdout unexpectedly")
        try:
            response = json.loads(line)
        except ValueError as exc:
            raise EditorSessionError(f"session {self.session_id!r} sent an unparseable response: {line!r}") from exc

        self.last_activity = time.monotonic()
        return response


class EditorSessionManager:
    """One instance lives for the whole life of the MCP server process,
    closed over by the ``editor_session`` tool -- sessions persist across
    separate tool calls, exactly like the config/other server state.
    """

    def __init__(self, cfg: ExpraMcpConfig, resolve_executable: Callable[[], tuple[str, str]]) -> None:
        self._cfg = cfg
        self._resolve_executable = resolve_executable
        self._sessions: dict[str, _EditorSession] = {}

    async def _launch_xvfb(self) -> tuple[asyncio.subprocess.Process, dict[str, str]]:
        xvfb_bin = shutil.which("Xvfb")
        if xvfb_bin is None:
            raise EditorSessionError("editor session needs Xvfb but the 'Xvfb' binary is not on PATH")

        display_num = _find_free_display_num()
        lock_path = Path(f"/tmp/.X{display_num}-lock")
        process = await asyncio.create_subprocess_exec(
            xvfb_bin, f":{display_num}", "-screen", "0", "1280x1024x24", "-nolisten", "tcp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if process.returncode is not None:
                raise EditorSessionError(f"Xvfb exited immediately (code {process.returncode})")
            if lock_path.exists():
                break
            await asyncio.sleep(0.1)
        else:
            process.kill()
            await process.wait()
            raise EditorSessionError(f"Xvfb did not start within 10s (display :{display_num})")

        env = dict(os.environ)
        env["DISPLAY"] = f":{display_num}"
        return process, env

    async def _prepare_launch(self) -> tuple[list[str], dict[str, str], asyncio.subprocess.Process | None]:
        mode = self._cfg.editor.display_mode
        display_set = bool(os.environ.get("DISPLAY"))
        executable, _ = self._resolve_executable()
        argv = [executable, str(_WORKER_PATH)]

        if mode == "native":
            if not display_set:
                raise EditorSessionError("editor.display_mode='native' requires $DISPLAY to be set")
            return argv, dict(os.environ), None

        if mode == "xvfb" or (mode == "auto" and not display_set):
            xvfb_process, env = await self._launch_xvfb()
            return argv, env, xvfb_process

        return argv, dict(os.environ), None

    async def start(self, *, expra_root: Path) -> tuple[str, dict[str, Any]]:
        await self._sweep_expired()

        try:
            argv, env, xvfb_process = await self._prepare_launch()
        except EditorSessionError as exc:
            return "", {"editor_session_available": False, "reason": str(exc)}

        env["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(expra_root / "src"), env.get("PYTHONPATH")]))

        async def _fail(reason: str) -> tuple[str, dict[str, Any]]:
            if xvfb_process is not None and xvfb_process.returncode is None:
                xvfb_process.kill()
                await xvfb_process.wait()
            return "", {"editor_session_available": False, "reason": reason}

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(expra_root),
            env=env,
        )
        assert process.stdout is not None

        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=20.0)
        except TimeoutError:
            process.kill()
            await process.wait()
            return await _fail("worker did not report ready within 20s")

        if not line:
            stderr_text = ""
            if process.stderr is not None:
                stderr_text = (await process.stderr.read()).decode("utf-8", errors="replace")[:2000]
            process.kill()
            await process.wait()
            return await _fail(f"worker exited immediately: {stderr_text}")

        try:
            handshake = json.loads(line)
        except ValueError:
            process.kill()
            await process.wait()
            return await _fail(f"worker sent an unparseable startup line: {line!r}")

        if not handshake.get("ok"):
            process.kill()
            await process.wait()
            return await _fail(handshake.get("error", "unknown startup failure"))

        session_id = uuid.uuid4().hex[:12]
        self._sessions[session_id] = _EditorSession(session_id, process, xvfb_process=xvfb_process)
        return session_id, {"editor_session_available": True, **handshake.get("data", {})}

    def _get(self, session_id: str) -> _EditorSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise EditorSessionError(f"unknown or already-closed session_id: {session_id!r}")
        return session

    async def send(self, session_id: str, command: str, params: dict[str, Any]) -> dict[str, Any]:
        session = self._get(session_id)
        timeout = float(self._cfg.execution.command_timeout_seconds)
        async with session.lock:
            response = await session.send(command, params, timeout=timeout)
        if command == "close":
            await self._terminate(session_id)
        return response

    async def _terminate(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        session.closed = True
        if session.process.returncode is None:
            try:
                if session.process.stdin is not None:
                    session.process.stdin.close()
                await asyncio.wait_for(session.process.wait(), timeout=5.0)
            except (TimeoutError, ConnectionError):
                session.process.kill()
                await session.process.wait()
        if session.xvfb_process is not None and session.xvfb_process.returncode is None:
            session.xvfb_process.kill()
            await session.xvfb_process.wait()

    async def _sweep_expired(self) -> None:
        timeout = self._cfg.editor.session_timeout_seconds
        now = time.monotonic()
        expired = [sid for sid, session in self._sessions.items() if now - session.last_activity > timeout]
        for sid in expired:
            await self._terminate(sid)

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            await self._terminate(session_id)
