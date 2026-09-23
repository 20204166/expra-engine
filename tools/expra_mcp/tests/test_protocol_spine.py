"""Phase 2A protocol-compliance spike.

These tests prove expra-mcp is genuinely speaking MCP -- not a JSON-RPC
lookalike -- by driving it exclusively through the official ``mcp`` SDK
Client, both in-process (server object directly) and over a real stdio
child-process connection. No test calls server-internal functions directly
as a substitute for a protocol round-trip.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys

import conftest
import pytest
from expra_dev_mcp.config import ExecutionConfig, ExpraMcpConfig, WorkspaceConfig
from expra_dev_mcp.server import build_server
from mcp import Client
from mcp.client.stdio import StdioServerParameters

REPO_ROOT = conftest.REPO_ROOT
REAL_CONFIG_PATH = REPO_ROOT / ".expra-mcp.toml"


def _in_repo_config() -> ExpraMcpConfig:
    """A config pointed at the real expra-engine checkout, built directly
    (bypassing file discovery) so these tests don't depend on the
    machine-local .expra-mcp.toml existing.
    """

    return ExpraMcpConfig(
        workspace=WorkspaceConfig(expra_root=REPO_ROOT, default_project="examples/blacksite_relay"),
        execution=ExecutionConfig(),
        config_path=REPO_ROOT / ".expra-mcp.test.toml",
    )


READINESS_VALUES = {"READY", "READY_WITH_LIMITATIONS", "NOT_READY"}


async def test_inprocess_client_discovers_and_calls_workspace_doctor() -> None:
    server = build_server(_in_repo_config())

    async with Client(server) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools.tools]
        assert "workspace_doctor" in names

        doctor_tool = next(t for t in tools.tools if t.name == "workspace_doctor")
        assert doctor_tool.annotations is not None
        assert doctor_tool.annotations.read_only_hint is True
        assert doctor_tool.annotations.destructive_hint is False

        result = await client.call_tool("workspace_doctor", {})
        assert result.is_error is not True
        assert result.structured_content is not None
        assert result.structured_content["readiness"] in READINESS_VALUES
        assert result.structured_content["server"]["name"] == "expra"
        # Real environment identity, not a stub: the configured Expra
        # interpreter must resolve to this repo's own .venv.
        assert ".venv" in result.structured_content["expra_python"]["executable"]


async def test_stdio_subprocess_client_connects_and_calls_workspace_doctor() -> None:
    if not REAL_CONFIG_PATH.is_file():
        pytest.skip("no .expra-mcp.toml at repo root -- run `expra-mcp init` first")

    env = dict(os.environ)
    env["EXPRA_MCP_CONFIG"] = str(REAL_CONFIG_PATH)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "expra_dev_mcp", "serve", "--transport", "stdio"],
        env=env,
        cwd=str(REPO_ROOT),
    )

    async with Client(params) as client:
        tools = await client.list_tools()
        assert "workspace_doctor" in [t.name for t in tools.tools]

        result = await client.call_tool("workspace_doctor", {})
        assert result.is_error is not True
        assert result.structured_content["readiness"] in READINESS_VALUES
        assert result.structured_content["server"]["name"] == "expra"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_streamable_http_client_connects_and_calls_workspace_doctor() -> None:
    """Real Streamable HTTP round-trip: spawn `expra-mcp serve --transport
    http`, connect over the wire, prove tools/list + tools/call work, and
    confirm the server negotiated a modern protocol version -- then clean up
    the child process regardless of outcome (spec: never leave a spawned
    server running after tests).
    """

    if not REAL_CONFIG_PATH.is_file():
        pytest.skip("no .expra-mcp.toml at repo root -- run `expra-mcp init` first")

    port = _free_port()
    env = dict(os.environ)
    env["EXPRA_MCP_CONFIG"] = str(REAL_CONFIG_PATH)

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "expra_dev_mcp",
        "serve",
        "--transport",
        "http",
        "--port",
        str(port),
        cwd=str(REPO_ROOT),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        last_error: Exception | None = None
        client: Client | None = None
        for _ in range(30):
            try:
                client = Client(url)
                await client.__aenter__()
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 -- retry-until-ready poll; the SDK can
                # raise several distinct connection-layer exceptions while the child
                # process is still binding its port, and we deliberately don't want to
                # hardcode which ones.
                last_error = exc
                await asyncio.sleep(0.2)
        if last_error is not None or client is None:
            pytest.fail(f"streamable-http server never became reachable: {last_error}")

        try:
            tools = await client.list_tools()
            assert "workspace_doctor" in [t.name for t in tools.tools]
            assert client.protocol_version is not None

            result = await client.call_tool("workspace_doctor", {})
            assert result.is_error is not True
            assert result.structured_content["readiness"] in READINESS_VALUES
        finally:
            await client.__aexit__(None, None, None)
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()
