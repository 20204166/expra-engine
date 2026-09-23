"""Safe subprocess execution shared by every tool that shells out.

Hard rules enforced here (spec sections 8/22): argument arrays only, never
``shell=True``; every call is timeout-bounded; output is byte-capped before
decoding so a runaway process can't flood model context.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    launch_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.launch_error is None and not self.timed_out and self.exit_code == 0


@dataclass
class ToolProbe:
    available: bool
    version: str | None
    path: str | None


async def run_command(
    argv: list[str],
    *,
    timeout_seconds: float = 15.0,
    max_output_bytes: int = 64 * 1024,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> CommandResult:
    """Run ``argv`` directly (never through a shell) and capture bounded
    stdout/stderr. Missing binaries and timeouts are reported as data, not
    raised, so callers can build structured results without try/except
    scattered everywhere. ``input_bytes``, when given, is written to the
    child's stdin (used to pass a JSON request to the static-inspection
    runner script without touching argv/env).
    """

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError:
        return CommandResult(argv=argv, exit_code=None, stdout="", stderr="", timed_out=False, launch_error="executable not found")
    except OSError as exc:
        return CommandResult(argv=argv, exit_code=None, stdout="", stderr="", timed_out=False, launch_error=str(exc))

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(input=input_bytes), timeout=timeout_seconds)
        timed_out = False
    except TimeoutError:
        proc.kill()
        await proc.wait()
        stdout_bytes, stderr_bytes = b"", b""
        timed_out = True

    stdout = stdout_bytes[:max_output_bytes].decode("utf-8", errors="replace")
    stderr = stderr_bytes[:max_output_bytes].decode("utf-8", errors="replace")
    return CommandResult(
        argv=argv,
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )


async def tool_version(argv: list[str], *, timeout_seconds: float = 10.0) -> ToolProbe:
    """Best-effort ``<tool> --version``-style probe. Resolves the binary on
    PATH first so a tool that exits non-zero on its version flag still
    reports ``available=True`` with a resolved path.
    """

    resolved_path = shutil.which(argv[0])
    if resolved_path is None:
        return ToolProbe(available=False, version=None, path=None)

    result = await run_command(argv, timeout_seconds=timeout_seconds)
    if result.launch_error or result.timed_out:
        return ToolProbe(available=False, version=None, path=resolved_path)

    text = (result.stdout or result.stderr).strip().splitlines()
    version_line = text[0] if text else None
    return ToolProbe(available=True, version=version_line, path=resolved_path)
