"""Environment/workspace identity gathering for ``workspace_doctor``.

This module never ``import expra_engine`` itself. All Expra-side identity
checks (module file/version, pygame, Tk) run as a subprocess under the
*configured* Expra interpreter, so this MCP server keeps working even when
Expra's own environment is broken (design point 6).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import command_runner, paths
from .config import ExpraMcpConfig
from .git_utils import git_identity
from .models import (
    ExpraIdentity,
    ProjectStatus,
    PygameIdentity,
    PythonIdentity,
    ReferenceStatus,
    ServerInfo,
    TkIdentity,
    ToolStatus,
    WorkspaceDoctorResult,
)

_EXPRA_PROBE_SCRIPT = r"""
import json
result = {}
try:
    import expra_engine
    result["module_file"] = getattr(expra_engine, "__file__", None)
    result["module_version"] = getattr(expra_engine, "__version__", None)
except Exception as exc:
    result["import_error"] = f"{type(exc).__name__}: {exc}"
try:
    import pygame
    result["pygame_installed"] = True
    result["pygame_version"] = pygame.version.ver
    result["pygame_file"] = getattr(pygame, "__file__", None)
except Exception as exc:
    result["pygame_installed"] = False
    result["pygame_error"] = f"{type(exc).__name__}: {exc}"
try:
    import tkinter
    result["tk_available"] = True
    result["tk_version"] = str(tkinter.TkVersion)
except Exception as exc:
    result["tk_available"] = False
    result["tk_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result))
"""


def resolve_configured_python(cfg: ExpraMcpConfig) -> tuple[str, str]:
    """Return ``(executable_path, resolved_via)`` for the configured Expra
    interpreter, per the conservative auto-resolution rule: prefer
    ``<expra_root>/.venv``, never a random system interpreter.
    """

    if cfg.workspace.python != "auto":
        return cfg.workspace.python, "config:explicit"
    venv = paths.venv_python(cfg.workspace.expra_root)
    if venv is not None:
        return str(venv), "auto:.venv"
    return sys.executable, "fallback:current_interpreter"


async def _python_identity(role: str, executable: str, resolved_via: str) -> PythonIdentity:
    result = await command_runner.run_command([executable, "--version"], timeout_seconds=10)
    version_text = (result.stdout or result.stderr).strip() or "unknown (probe failed)"
    return PythonIdentity(role=role, executable=executable, version=version_text, resolved_via=resolved_via)


async def _expra_probe(executable: str, expra_root: Path) -> tuple[ExpraIdentity, PygameIdentity, TkIdentity]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(expra_root / "src"), env.get("PYTHONPATH")]))

    result = await command_runner.run_command([executable, "-c", _EXPRA_PROBE_SCRIPT], timeout_seconds=20, env=env)

    def _failure(error: str) -> tuple[ExpraIdentity, PygameIdentity, TkIdentity]:
        return (
            ExpraIdentity(root=str(expra_root), import_error=error),
            PygameIdentity(installed=False, error=error),
            TkIdentity(available=False, error=error),
        )

    if not result.ok:
        return _failure(result.launch_error or (result.stderr.strip() or "probe failed with no output"))

    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        return _failure(f"could not parse probe output: {exc}")

    module_file = data.get("module_file")
    imported_from_source = paths.is_contained(Path(module_file), expra_root / "src") if module_file else None
    git_commit, git_dirty = await git_identity(expra_root)

    expra = ExpraIdentity(
        root=str(expra_root),
        git_commit=git_commit,
        git_dirty=git_dirty,
        module_file=module_file,
        module_version=data.get("module_version"),
        imported_from_configured_source=imported_from_source,
        import_error=data.get("import_error"),
    )
    pygame_identity = PygameIdentity(
        installed=data.get("pygame_installed", False),
        version=data.get("pygame_version"),
        module_file=data.get("pygame_file"),
        error=data.get("pygame_error"),
    )
    tk_identity = TkIdentity(
        available=data.get("tk_available", False),
        tcl_tk_version=data.get("tk_version"),
        display=os.environ.get("DISPLAY"),
        wayland_display=os.environ.get("WAYLAND_DISPLAY"),
        error=data.get("tk_error"),
    )
    return expra, pygame_identity, tk_identity


async def _system_tool_statuses() -> list[ToolStatus]:
    checks: list[tuple[str, list[str]]] = [
        ("rg", ["rg", "--version"]),
        ("git", ["git", "--version"]),
        ("xvfb-run", ["xvfb-run", "--help"]),
    ]
    results = []
    for name, argv in checks:
        probe = await command_runner.tool_version(argv)
        results.append(ToolStatus(name=name, available=probe.available, version=probe.version, path=probe.path))
    return results


async def _configured_python_tool_statuses(executable: str) -> list[ToolStatus]:
    checks: list[tuple[str, list[str]]] = [
        ("pytest", [executable, "-m", "pytest", "--version"]),
        ("ruff", [executable, "-m", "ruff", "--version"]),
        ("pyright", [executable, "-m", "pyright", "--version"]),
        ("mypy", [executable, "-m", "mypy", "--version"]),
    ]
    results = []
    for name, argv in checks:
        result = await command_runner.run_command(argv, timeout_seconds=15)
        if result.ok:
            text = (result.stdout or result.stderr).strip().splitlines()
            results.append(ToolStatus(name=name, available=True, version=text[0] if text else None, path=executable))
        else:
            results.append(ToolStatus(name=name, available=False, version=None, path=None))
    return results


async def _reference_statuses(cfg: ExpraMcpConfig) -> list[ReferenceStatus]:
    statuses = []
    for ref_id, ref in cfg.references.items():
        exists = ref.path.exists()
        is_checkout = (ref.path / ".git").exists() if exists else False
        revision = None
        if is_checkout:
            revision, _ = await git_identity(ref.path)
        statuses.append(
            ReferenceStatus(
                id=ref_id,
                path=str(ref.path),
                exists=exists,
                read_only=True,  # enforced in code regardless of config value
                domains=ref.domains,
                git_revision=revision,
                is_git_checkout=is_checkout,
            )
        )
    return statuses


async def gather_workspace_doctor(cfg: ExpraMcpConfig, *, server_name: str, server_version: str) -> WorkspaceDoctorResult:
    expra_executable, resolved_via = resolve_configured_python(cfg)

    mcp_python = await _python_identity("mcp_server", sys.executable, "self")
    expra_python = await _python_identity("expra", expra_executable, resolved_via)
    expra_identity, pygame_identity, tk_identity = await _expra_probe(expra_executable, cfg.workspace.expra_root)

    tool_statuses = await _system_tool_statuses()
    tool_statuses += await _configured_python_tool_statuses(expra_executable)

    default_project_status = None
    if cfg.workspace.default_project:
        project_path = cfg.workspace.expra_root / cfg.workspace.default_project
        default_project_status = ProjectStatus(
            id=cfg.workspace.default_project, path=str(project_path), exists=project_path.is_dir()
        )

    reference_statuses = await _reference_statuses(cfg)

    reasons: list[str] = []
    if expra_identity.import_error:
        reasons.append(f"expra_engine failed to import under the configured interpreter: {expra_identity.import_error}")
    if expra_identity.imported_from_configured_source is False:
        reasons.append(
            f"expra_engine imported from {expra_identity.module_file!r}, NOT from "
            f"{cfg.workspace.expra_root / 'src'} -- a stale installed package may be shadowing the source tree"
        )
    if not pygame_identity.installed:
        reasons.append("pygame is not installed in the configured Expra interpreter")
    if not tk_identity.available:
        reasons.append("Tk is not available in the configured Expra interpreter -- editor_session will be unavailable")
    if default_project_status is not None and not default_project_status.exists:
        reasons.append(f"configured default_project does not exist: {default_project_status.path}")
    missing_refs = [r.id for r in reference_statuses if not r.exists]
    if missing_refs:
        reasons.append(f"reference roots missing on disk: {', '.join(missing_refs)}")

    if expra_identity.import_error or expra_identity.imported_from_configured_source is False:
        readiness = "NOT_READY"
    elif reasons:
        readiness = "READY_WITH_LIMITATIONS"
    else:
        readiness = "READY"

    server_info = ServerInfo(
        name=server_name,
        version=server_version,
        config_path=str(cfg.config_path),
        artifact_directory=str(cfg.artifacts_dir()),
        diagnostics_directory=str(cfg.diagnostics_dir()),
    )

    return WorkspaceDoctorResult(
        readiness=readiness,
        reasons=reasons,
        server=server_info,
        mcp_server_python=mcp_python,
        expra_python=expra_python,
        expra=expra_identity,
        pygame=pygame_identity,
        tk=tk_identity,
        tools=tool_statuses,
        default_project=default_project_status,
        references=reference_statuses,
    )
