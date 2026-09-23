"""Proves expra-mcp stays outside Expra's runtime/export dependency closure
(spec section 11): nothing under src/expra_engine may import mcp or
expra_dev_mcp, and expra-engine's own pyproject.toml must not depend on them.
"""

from __future__ import annotations

import re
import tomllib

import conftest

REPO_ROOT = conftest.REPO_ROOT
FORBIDDEN_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+(mcp|expra_dev_mcp)\b", re.MULTILINE)


def test_no_engine_source_file_imports_mcp() -> None:
    engine_src = REPO_ROOT / "src" / "expra_engine"
    offenders = []
    for path in engine_src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN_IMPORT_RE.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"expra_engine source imports mcp/expra_dev_mcp: {offenders}"


def test_engine_pyproject_has_no_mcp_dependency() -> None:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})

    all_deps: list[str] = list(project.get("dependencies", []))
    for group_deps in project.get("optional-dependencies", {}).values():
        all_deps.extend(group_deps)

    forbidden_names = {"mcp", "expra-mcp", "expra_dev_mcp"}
    offenders = [dep for dep in all_deps if dep.split(">")[0].split("=")[0].split("<")[0].strip() in forbidden_names]
    assert offenders == [], f"expra-engine pyproject.toml depends on MCP tooling: {offenders}"


def test_export_closure_modules_do_not_import_mcp() -> None:
    export_dir = REPO_ROOT / "src" / "expra_engine" / "export"
    assert export_dir.is_dir(), "expra_engine/export directory not found -- update this test if it moved"
    offenders = []
    for path in export_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN_IMPORT_RE.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"export closure imports mcp/expra_dev_mcp: {offenders}"
