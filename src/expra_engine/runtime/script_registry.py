"""Explicit project Behaviour loader using normal import machinery."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import TypeVar

from expra_engine.filesystem import ResourceId
from expra_engine.runtime.behaviour import Behaviour

B = TypeVar("B", bound=Behaviour)


class ScriptLoadError(RuntimeError):
    """A project script could not be resolved or validated."""


class ScriptRegistry:
    """Resolve only approved ``project://`` Python resources."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self._modules: dict[str, types.ModuleType] = {}
        self._generations: dict[str, int] = {}

    def resolve(self, script_id: ResourceId | str, class_name: str) -> type[Behaviour]:
        resource = self._resource(script_id)
        module = self._load(resource)
        candidate = getattr(module, class_name, None)
        if not isinstance(candidate, type) or not issubclass(candidate, Behaviour):
            raise ScriptLoadError(f"{resource}: {class_name!r} is not a Behaviour class")
        return candidate

    def reload(self, script_id: ResourceId | str) -> int:
        resource = self._resource(script_id)
        key = str(resource)
        old = self._modules.pop(key, None)
        module_name = old.__name__ if old is not None else None
        try:
            self._load(resource)
        except Exception:
            if old is not None:
                self._modules[key] = old
                sys.modules[old.__name__] = old
            raise
        self._generations[key] = self._generations.get(key, 0) + 1
        if module_name is not None and module_name != self._modules[key].__name__:
            sys.modules.pop(module_name, None)
        return self._generations[key]

    def generation(self, script_id: ResourceId | str) -> int:
        return self._generations.get(str(self._resource(script_id)), 0)

    def _resource(self, value: ResourceId | str) -> ResourceId:
        try:
            resource = value if isinstance(value, ResourceId) else ResourceId.parse(value)
        except Exception as exc:
            raise ScriptLoadError(f"invalid script resource: {value!r}") from exc
        if resource.scheme != "project" or not resource.path.startswith("scripts/"):
            raise ScriptLoadError(f"script resource must be project://scripts/: {resource}")
        if not resource.path.endswith(".py"):
            raise ScriptLoadError(f"script resource must be Python: {resource}")
        path = (self.project_root / resource.path).resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ScriptLoadError(f"script escapes project root: {resource}") from exc
        if not path.is_file():
            raise ScriptLoadError(f"script not found: {resource}")
        return resource

    def _load(self, resource: ResourceId) -> types.ModuleType:
        key = str(resource)
        cached = self._modules.get(key)
        if cached is not None:
            return cached
        digest = hashlib.sha256(str(self.project_root).encode()).hexdigest()[:16]
        package = f"_expra_project_{digest}"
        path = self.project_root / resource.path
        parts = resource.path.split("/")[:-1]
        parent = package
        for index, part in enumerate(parts):
            parent = f"{parent}.{part}"
            if parent not in sys.modules:
                module = types.ModuleType(parent)
                module.__path__ = [str(self.project_root / "/".join(parts[: index + 1]))]
                sys.modules[parent] = module
        module_name = f"{package}.{resource.path[:-3].replace('/', '.')}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ScriptLoadError(f"could not load script: {resource}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise ScriptLoadError(f"script import failed: {resource}") from exc
        self._modules[key] = module
        return module


__all__ = ["ScriptLoadError", "ScriptRegistry"]
