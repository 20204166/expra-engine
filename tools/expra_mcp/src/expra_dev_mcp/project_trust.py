"""Trusted-project-root enforcement for tools that execute project code.

Static tools (expra_inspect, render_inspect, resource_trace, render_snapshot)
never execute project code and are NOT gated by this -- only tools that
actually run project-authored Behaviour scripts are: runtime_probe now,
editor_session in Phase 2F. Default trusted root is exactly ``examples/``,
confirmed to hold all three real example projects and nothing else in this
repo (spec: "Default should include only <expra_root>/examples").
"""

from __future__ import annotations

from pathlib import Path

from . import paths
from .config import ExpraMcpConfig


def resolve_trusted_roots(cfg: ExpraMcpConfig) -> list[Path]:
    return [(cfg.workspace.expra_root / root).resolve() for root in cfg.workspace.trusted_project_roots]


def is_trusted_project(cfg: ExpraMcpConfig, project: str) -> bool:
    project_path = (cfg.workspace.expra_root / project).resolve()
    return any(paths.is_contained(project_path, root) for root in resolve_trusted_roots(cfg))
