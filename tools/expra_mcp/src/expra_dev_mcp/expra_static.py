"""Bridge to ``_static_runner.py``, executed under the CONFIGURED Expra
interpreter via subprocess -- this module (and everything that calls it)
never imports expra_engine into the MCP server's own process.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import command_runner

_RUNNER_PATH = Path(__file__).with_name("_static_runner.py")


class StaticInspectionError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


async def run_static_op(executable: str, expra_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    payload = dict(request)
    payload["expra_root"] = str(expra_root)

    env = dict(os.environ)
    env["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"  # belt-and-suspenders; the runner also sets this itself
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(expra_root / "src"), env.get("PYTHONPATH")]))

    result = await command_runner.run_command(
        [executable, str(_RUNNER_PATH)],
        timeout_seconds=30,
        max_output_bytes=8 * 1024 * 1024,
        env=env,
        input_bytes=json.dumps(payload).encode("utf-8"),
    )
    if not result.ok:
        error = result.launch_error or (result.stderr.strip() or "static inspection runner failed with no output")
        raise StaticInspectionError("runner_failure", error)

    # Defense in depth against stray stdout chatter (e.g. a library banner
    # the PYGAME_HIDE_SUPPORT_PROMPT suppression above doesn't cover): the
    # runner's own JSON is always its single final line.
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise StaticInspectionError("bad_response", "static inspection runner produced no output")
    try:
        envelope = json.loads(lines[-1])
    except ValueError as exc:
        raise StaticInspectionError("bad_response", f"could not parse runner output: {exc}") from exc

    if not envelope.get("ok"):
        raise StaticInspectionError(envelope.get("kind", "unknown"), envelope.get("error", "static inspection failed"))

    return envelope["data"]
