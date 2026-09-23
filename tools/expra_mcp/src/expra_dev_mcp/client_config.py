"""Client configuration emitters. Print by default; ``--write`` is the only
path that mutates a file, per the spec's "do not silently mutate another
application's global config" rule.

Phase 2A implemented OpenCode (this project's priority client) against its
real installed config schema. Phase 2G adds VS Code, Cursor, Claude Code,
and Codex, each verified against that client's real current documentation
at implementation time (not the original spec's illustrative examples) --
notably: VS Code's workspace schema key is "servers" (not "mcpServers");
Cursor's is "mcpServers"; Claude Code's CLI requires a literal "--"
separator between its own flags and the server command; Codex's TOML block
uses "args" as an array plus a nested "[mcp_servers.NAME.env]" table.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

from .config import ExpraMcpConfig

SUPPORTED_CLIENTS = ("opencode", "vscode", "cursor", "claude-code", "codex", "generic")


def _server_command(cfg: ExpraMcpConfig) -> list[str]:
    tool_root = Path(__file__).resolve().parents[2]  # tools/expra_mcp/
    if platform.system() == "Windows":
        python = tool_root / ".venv" / "Scripts" / "python.exe"
    else:
        python = tool_root / ".venv" / "bin" / "python"
    return [str(python), "-m", "expra_dev_mcp", "serve", "--transport", "stdio"]


def emit_opencode(cfg: ExpraMcpConfig) -> str:
    payload = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "servers": {
                "expra": {
                    "type": "local",
                    "command": _server_command(cfg),
                    "cwd": str(cfg.workspace.expra_root),
                    "environment": {"EXPRA_MCP_CONFIG": str(cfg.config_path)},
                    "enabled": True,
                }
            }
        },
    }
    return json.dumps(payload, indent=2)


def emit_vscode(cfg: ExpraMcpConfig) -> str:
    command = _server_command(cfg)
    payload = {
        "servers": {
            "expra": {
                "type": "stdio",
                "command": command[0],
                "args": command[1:],
                "env": {"EXPRA_MCP_CONFIG": str(cfg.config_path)},
            }
        }
    }
    return json.dumps(payload, indent=2)


def emit_cursor(cfg: ExpraMcpConfig) -> str:
    command = _server_command(cfg)
    payload = {
        "mcpServers": {
            "expra": {
                "command": command[0],
                "args": command[1:],
                "env": {"EXPRA_MCP_CONFIG": str(cfg.config_path)},
            }
        }
    }
    return json.dumps(payload, indent=2)


def emit_claude_code(cfg: ExpraMcpConfig, *, scope: str) -> str:
    command = _server_command(cfg)
    cli_scope = "project" if scope == "project" else "user"
    args_str = " ".join(command[1:])
    resulting_json = json.dumps(
        {
            "mcpServers": {
                "expra": {
                    "command": command[0],
                    "args": command[1:],
                    "env": {"EXPRA_MCP_CONFIG": str(cfg.config_path)},
                }
            }
        },
        indent=2,
    )
    return "\n".join(
        [
            "claude mcp add \\",
            f"  --env EXPRA_MCP_CONFIG={cfg.config_path} \\",
            f"  --scope {cli_scope} \\",
            "  expra \\",
            f"  -- {command[0]} {args_str}",
            "",
            "Resulting config (.mcp.json for --scope project, ~/.claude.json for --scope user):",
            resulting_json,
        ]
    )


def emit_codex(cfg: ExpraMcpConfig) -> str:
    command = _server_command(cfg)
    args_str = " ".join(command[1:])
    args_toml = "[" + ", ".join(f'"{a}"' for a in command[1:]) + "]"
    toml_block = "\n".join(
        [
            "[mcp_servers.expra]",
            f'command = "{command[0]}"',
            f"args = {args_toml}",
            "",
            "[mcp_servers.expra.env]",
            f'EXPRA_MCP_CONFIG = "{cfg.config_path}"',
        ]
    )
    return "\n".join(
        [
            f"codex mcp add expra --env EXPRA_MCP_CONFIG={cfg.config_path} -- {command[0]} {args_str}",
            "",
            "Resulting config.toml block:",
            toml_block,
        ]
    )


def emit_generic(cfg: ExpraMcpConfig) -> str:
    command = _server_command(cfg)
    lines = [
        "Generic MCP client configuration for expra-mcp",
        "",
        "stdio (recommended for local development -- no ports, no auth):",
        f"  command: {command[0]}",
        f"  args:    {command[1:]}",
        f"  cwd:     {cfg.workspace.expra_root}",
        f"  env:     EXPRA_MCP_CONFIG={cfg.config_path}",
        "",
        "Streamable HTTP (remote/container/WSL-boundary use; binds 127.0.0.1 by default):",
        f"  command: {command[0]} -m expra_dev_mcp serve --transport http --host 127.0.0.1 --port 8000",
        "  url:     http://127.0.0.1:8000/mcp",
    ]
    return "\n".join(lines)


def emit(client: str, cfg: ExpraMcpConfig, *, scope: str) -> str:
    if client == "opencode":
        return emit_opencode(cfg)
    if client == "vscode":
        return emit_vscode(cfg)
    if client == "cursor":
        return emit_cursor(cfg)
    if client == "claude-code":
        return emit_claude_code(cfg, scope=scope)
    if client == "codex":
        return emit_codex(cfg)
    if client == "generic":
        return emit_generic(cfg)
    raise ValueError(f"unsupported client: {client!r} (supported: {SUPPORTED_CLIENTS})")


def write_target(client: str, cfg: ExpraMcpConfig, *, scope: str) -> Path:
    if client == "opencode":
        if scope == "project":
            return cfg.workspace.expra_root / "opencode.json"
        return Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if client == "vscode":
        if scope != "project":
            raise ValueError("client='vscode' only supports --scope project (workspace .vscode/mcp.json)")
        return cfg.workspace.expra_root / ".vscode" / "mcp.json"
    if client == "cursor":
        if scope == "project":
            return cfg.workspace.expra_root / ".cursor" / "mcp.json"
        return Path.home() / ".cursor" / "mcp.json"
    raise ValueError(
        f"--write is not supported for client: {client!r} -- run the printed command "
        "or paste the printed config manually"
    )
