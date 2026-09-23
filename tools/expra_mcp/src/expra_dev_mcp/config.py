"""Portable TOML configuration: discovery, parsing, and a minimal writer for
``expra-mcp init`` / ``expra-mcp config emit``.

Reading uses the stdlib ``tomllib`` (Python 3.11+, no extra dependency).
Writing is a small hand-rolled serializer scoped to exactly this config's
shape -- not a general TOML writer -- since the schema is fixed and small.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from . import paths

CONFIG_ENV_VAR = "EXPRA_MCP_CONFIG"
PROJECT_LOCAL_FILENAME = ".expra-mcp.toml"


class ReferenceConfig(BaseModel):
    path: Path
    read_only: bool = True
    domains: list[str] = Field(default_factory=list)


class WorkspaceConfig(BaseModel):
    expra_root: Path
    default_project: str | None = None
    python: str = "auto"
    trusted_project_roots: list[str] = Field(default_factory=lambda: ["examples"])


class ExecutionConfig(BaseModel):
    allow_source_writes: bool = False
    allow_network: bool = False
    command_timeout_seconds: int = 600
    max_output_kb: int = 256
    max_parallel_commands: int = 2


class EditorConfig(BaseModel):
    display_mode: str = "auto"
    default_width: int = 1280
    default_height: int = 720
    session_timeout_seconds: int = 1800


class ArtifactsConfig(BaseModel):
    directory: str = ".expra-mcp/artifacts"


class DiagnosticsConfig(BaseModel):
    directory: str = ".expra-mcp/runs"
    deduplicate: bool = True


class ExpraMcpConfig(BaseModel):
    schema_version: int = 1
    workspace: WorkspaceConfig
    references: dict[str, ReferenceConfig] = Field(default_factory=dict)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    artifacts: ArtifactsConfig = Field(default_factory=ArtifactsConfig)
    diagnostics: DiagnosticsConfig = Field(default_factory=DiagnosticsConfig)

    config_path: Path = Field(exclude=True)

    def artifacts_dir(self) -> Path:
        return paths.resolve_path(self.artifacts.directory, base_dir=self.workspace.expra_root)

    def diagnostics_dir(self) -> Path:
        return paths.resolve_path(self.diagnostics.directory, base_dir=self.workspace.expra_root)


class ConfigError(RuntimeError):
    pass


def discover_config_path(explicit: Path | None = None) -> Path:
    """Resolution order: ``--config`` > ``$EXPRA_MCP_CONFIG`` > project-local
    ``./.expra-mcp.toml`` > OS user config directory.
    """

    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"--config path does not exist: {explicit}")
        return explicit.resolve()

    env_value = os.environ.get(CONFIG_ENV_VAR)
    if env_value:
        env_path = Path(env_value).expanduser()
        if not env_path.is_file():
            raise ConfigError(f"${CONFIG_ENV_VAR} points to a missing file: {env_path}")
        return env_path.resolve()

    project_local = Path.cwd() / PROJECT_LOCAL_FILENAME
    if project_local.is_file():
        return project_local.resolve()

    user_path = paths.user_config_dir() / "config.toml"
    if user_path.is_file():
        return user_path.resolve()

    raise ConfigError(
        "No expra-mcp config found. Checked --config, $EXPRA_MCP_CONFIG, "
        f"./{PROJECT_LOCAL_FILENAME}, and {user_path}. Run `expra-mcp init` first."
    )


def _expand_raw_paths(data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Apply ``~``/relative expansion to path-shaped fields before pydantic
    validation. ``${ENV}`` substitution already happened on the raw TOML text
    in :func:`load_config`.
    """

    data = dict(data)
    workspace = dict(data.get("workspace", {}))
    if "expra_root" in workspace:
        workspace["expra_root"] = str(paths.resolve_path(workspace["expra_root"], base_dir=base_dir))
    data["workspace"] = workspace

    references = data.get("references", {})
    if references:
        expanded_refs: dict[str, Any] = {}
        for ref_id, ref in references.items():
            ref = dict(ref)
            if "path" in ref:
                ref["path"] = str(paths.resolve_path(ref["path"], base_dir=base_dir))
            expanded_refs[ref_id] = ref
        data["references"] = expanded_refs

    return data


def load_config(explicit_path: Path | None = None) -> ExpraMcpConfig:
    config_path = discover_config_path(explicit_path)
    raw_text = config_path.read_text(encoding="utf-8")
    raw_text = paths.expand_env_vars(raw_text)
    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc

    data = _expand_raw_paths(data, base_dir=config_path.parent)

    try:
        return ExpraMcpConfig(config_path=config_path, **data)
    except Exception as exc:  # pydantic ValidationError, etc.
        raise ConfigError(f"Invalid expra-mcp config at {config_path}: {exc}") from exc


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_initial_config(
    *,
    expra_root: Path,
    default_project: str | None,
    references: dict[str, Path],
) -> str:
    """Render a valid, schema_version=1 config for ``expra-mcp init``."""

    lines = ["schema_version = 1", "", "[workspace]", f"expra_root = {_toml_string(str(expra_root))}"]
    if default_project:
        lines.append(f"default_project = {_toml_string(default_project)}")
    lines.append('python = "auto"')
    lines.append('trusted_project_roots = ["examples"]')
    lines.append("")

    for ref_id, ref_path in references.items():
        lines.append(f"[references.{ref_id}]")
        lines.append(f"path = {_toml_string(str(ref_path))}")
        lines.append("read_only = true")
        lines.append("domains = []")
        lines.append("")

    lines += [
        "[execution]",
        "allow_source_writes = false",
        "allow_network = false",
        "command_timeout_seconds = 600",
        "max_output_kb = 256",
        "max_parallel_commands = 2",
        "",
        "[editor]",
        'display_mode = "auto"',
        "default_width = 1280",
        "default_height = 720",
        "session_timeout_seconds = 1800",
        "",
        "[artifacts]",
        'directory = ".expra-mcp/artifacts"',
        "",
        "[diagnostics]",
        'directory = ".expra-mcp/runs"',
        "deduplicate = true",
        "",
    ]
    return "\n".join(lines)
