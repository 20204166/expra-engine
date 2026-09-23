"""Unit tests for client_config.py's emitters. No existing tests covered
this module before Phase 2G (opencode's Phase 2A verification relied on a
live `opencode mcp list` connectivity check instead) -- this file closes
that gap for all five clients now that four more have been added.
"""

from __future__ import annotations

import json

import conftest
import pytest
from expra_dev_mcp import client_config
from expra_dev_mcp.config import ExpraMcpConfig, WorkspaceConfig

REPO_ROOT = conftest.REPO_ROOT


def _cfg() -> ExpraMcpConfig:
    return ExpraMcpConfig(
        workspace=WorkspaceConfig(expra_root=REPO_ROOT),
        config_path=REPO_ROOT / ".expra-mcp.test.toml",
    )


def test_supported_clients_lists_all_five() -> None:
    assert set(client_config.SUPPORTED_CLIENTS) == {"opencode", "vscode", "cursor", "claude-code", "codex", "generic"}


def test_opencode_schema_has_no_protocol_field() -> None:
    # Regression guard: the original spec's illustrative example included a
    # "protocol" field that does not exist in OpenCode's real schema
    # (confirmed against live docs in Phase 2A) -- this must never come back.
    payload = json.loads(client_config.emit_opencode(_cfg()))
    server = payload["mcp"]["servers"]["expra"]
    assert "protocol" not in server
    assert server["type"] == "local"
    assert isinstance(server["command"], list)


def test_vscode_schema_uses_servers_key() -> None:
    payload = json.loads(client_config.emit_vscode(_cfg()))
    assert "servers" in payload
    assert "mcpServers" not in payload
    server = payload["servers"]["expra"]
    assert server["type"] == "stdio"
    assert isinstance(server["command"], str)
    assert isinstance(server["args"], list)


def test_cursor_schema_uses_mcp_servers_key() -> None:
    payload = json.loads(client_config.emit_cursor(_cfg()))
    assert "mcpServers" in payload
    assert "servers" not in payload
    server = payload["mcpServers"]["expra"]
    assert isinstance(server["command"], str)
    assert isinstance(server["args"], list)


def test_claude_code_emits_double_dash_separator() -> None:
    text = client_config.emit_claude_code(_cfg(), scope="project")
    assert "claude mcp add" in text
    assert " -- " in text
    assert "--scope project" in text
    # everything after "--" must be exactly the real server command, untouched
    after_separator = text.split(" -- ", 1)[1].splitlines()[0]
    assert after_separator.strip().endswith("serve --transport stdio")


def test_codex_emits_toml_block_with_nested_env_table() -> None:
    text = client_config.emit_codex(_cfg())
    assert "codex mcp add expra" in text
    assert "[mcp_servers.expra]" in text
    assert "[mcp_servers.expra.env]" in text
    assert 'command = "' in text
    assert "args = [" in text


def test_generic_emitter_still_works() -> None:
    text = client_config.emit_generic(_cfg())
    assert "stdio" in text
    assert "Streamable HTTP" in text


def test_emit_unknown_client_raises() -> None:
    with pytest.raises(ValueError):
        client_config.emit("not-a-real-client", _cfg(), scope="project")


def test_write_target_vscode_project_scope() -> None:
    target = client_config.write_target("vscode", _cfg(), scope="project")
    assert target == REPO_ROOT / ".vscode" / "mcp.json"


def test_write_target_vscode_rejects_user_scope() -> None:
    with pytest.raises(ValueError):
        client_config.write_target("vscode", _cfg(), scope="user")


def test_write_target_cursor_project_and_user_scope() -> None:
    project_target = client_config.write_target("cursor", _cfg(), scope="project")
    assert project_target == REPO_ROOT / ".cursor" / "mcp.json"
    user_target = client_config.write_target("cursor", _cfg(), scope="user")
    assert user_target.name == "mcp.json"
    assert ".cursor" in user_target.parts


def test_write_target_claude_code_and_codex_are_not_writable() -> None:
    # These are CLI-driven (the real client's own CLI writes its own config
    # when the printed command is actually run) -- expra-mcp never writes
    # for them directly.
    with pytest.raises(ValueError):
        client_config.write_target("claude-code", _cfg(), scope="project")
    with pytest.raises(ValueError):
        client_config.write_target("codex", _cfg(), scope="project")
