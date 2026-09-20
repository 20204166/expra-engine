"""Safe editor operations for creating and attaching project scripts."""

from __future__ import annotations

import keyword
from pathlib import Path

from expra_engine.core.entity import Entity
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.script_component import ScriptComponent


def create_behaviour_script(project_root: Path, relative_path: str, class_name: str) -> ResourceId:
    """Create a minimal script without overwriting or escaping the project."""
    if not class_name.isidentifier() or keyword.iskeyword(class_name):
        raise ValueError(f"invalid Behaviour class name: {class_name!r}")
    resource = ResourceId.from_project_path(relative_path, scheme="project")
    if not resource.path.startswith("scripts/") or not resource.path.endswith(".py"):
        raise ValueError("scripts must be project://scripts/*.py")
    path = (project_root.resolve() / resource.path).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError("script path escapes project root") from exc
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "from expra_engine.runtime.behaviour import Behaviour, exposed\n\n\n"
        f"class {class_name}(Behaviour):\n"
        "    speed = exposed(100.0, min=0.0)\n\n"
        "    def on_update(self, dt: float) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )
    return resource


def attach_script(entity: Entity, script_id: ResourceId | str, class_name: str) -> ScriptComponent:
    """Attach one declarative script component, rejecting duplicates."""
    resource = script_id if isinstance(script_id, ResourceId) else ResourceId.parse(script_id)
    if (
        resource.scheme != "project"
        or not resource.path.startswith("scripts/")
        or not resource.path.endswith(".py")
    ):
        raise ValueError("scripts must be project://scripts/*.py")
    if not class_name.isidentifier() or keyword.iskeyword(class_name):
        raise ValueError(f"invalid Behaviour class name: {class_name!r}")
    for component in entity.components:
        if isinstance(component, ScriptComponent) and (
            component.script_id == resource and component.behaviour_class == class_name
        ):
            raise ValueError("Behaviour is already attached")
    component = ScriptComponent(resource, class_name)
    entity.add_component(component)
    return component


__all__ = ["attach_script", "create_behaviour_script"]
