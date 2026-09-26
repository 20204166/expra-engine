"""Shared example-project Engine bootstrap for dogfood acceptance tests."""

from __future__ import annotations

from pathlib import Path

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.runtime.script_registry import ScriptRegistry


def load_project_engine(project_dir: Path) -> tuple[Project, Engine]:
    """Load *project_dir* and return a ready-to-run (Project, Engine) pair."""
    project = Project.load(project_dir)
    engine = Engine()
    engine.set_project(project)
    engine.set_script_registry(ScriptRegistry(project.path))
    engine.set_scene(project.load_document())
    return project, engine
