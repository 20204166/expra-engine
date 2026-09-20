"""verify_export(): verifies a completed export build. Fails closed."""

from __future__ import annotations

import ast
import dis
import json
import marshal
from pathlib import Path
from types import CodeType

_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "tkinter",
    "ttkbootstrap",
    "expra_engine.editor",
    "expra_engine.ui",
    "expra_engine.design",
    "ursina",
    "panda3d",
)

_REQUIRED_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "game_name",
        "game_version",
        "engine_version",
        "target",
        "python_version",
        "arch",
        "compile_bytecode",
        "entry_point",
        "build_timestamp",
        "runtime_profile",
    }
)


class ExportVerificationError(RuntimeError):
    pass


def _is_forbidden_import(module: str, forbidden: str) -> bool:
    return module == forbidden or module.startswith(f"{forbidden}.")


def _scan_for_forbidden_imports(export_dir: Path) -> list[str]:
    """Return paths and imports that must not ship in a game export."""
    violations: list[str] = []
    for py_file in export_dir.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError):
            continue

        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)

        for module in imported_modules:
            for forbidden in _FORBIDDEN_IMPORTS:
                if _is_forbidden_import(module, forbidden):
                    relative_path = py_file.relative_to(export_dir)
                    violations.append(f"{relative_path}: forbidden import '{module}'")
                    break
    for pyc_file in export_dir.rglob("*.pyc"):
        try:
            with pyc_file.open("rb") as stream:
                stream.read(16)
                code = marshal.load(stream)
        except (OSError, EOFError, ValueError, TypeError):
            continue
        for module in _iter_imports(code):
            for forbidden in _FORBIDDEN_IMPORTS:
                if _is_forbidden_import(module, forbidden):
                    relative_path = pyc_file.relative_to(export_dir)
                    violations.append(f"{relative_path}: forbidden import '{module}'")
                    break
    return violations


def _iter_imports(code: object):
    """Yield import names from a compiled code object and nested functions."""
    if not isinstance(code, CodeType):
        return
    for instruction in dis.get_instructions(code):
        if instruction.opname == "IMPORT_NAME" and isinstance(instruction.argval, str):
            yield instruction.argval
    for constant in getattr(code, "co_consts", ()):
        if hasattr(constant, "co_code"):
            yield from _iter_imports(constant)


def verify_export(build_dir: Path) -> None:
    """Verify a completed export build. Raises ExportVerificationError on any problem.

    Checks:
    - build directory exists
    - build_manifest.json is present and valid JSON with required keys
    - asset_manifest.json is present and valid JSON
    """
    if not build_dir.is_dir():
        raise ExportVerificationError(f"Build directory does not exist: {build_dir}")

    build_manifest_path = build_dir / "build_manifest.json"
    if not build_manifest_path.exists():
        raise ExportVerificationError(f"Missing build_manifest.json in {build_dir}")

    try:
        build_manifest = json.loads(build_manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ExportVerificationError(f"Cannot parse build_manifest.json: {e}") from e

    missing = _REQUIRED_MANIFEST_KEYS - build_manifest.keys()
    if missing:
        raise ExportVerificationError(
            f"build_manifest.json missing required keys: {sorted(missing)}"
        )

    asset_manifest_path = build_dir / "asset_manifest.json"
    if not asset_manifest_path.exists():
        raise ExportVerificationError(f"Missing asset_manifest.json in {build_dir}")

    try:
        asset_data = json.loads(asset_manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ExportVerificationError(f"Cannot parse asset_manifest.json: {e}") from e

    if "entries" not in asset_data:
        raise ExportVerificationError("asset_manifest.json missing 'entries' key")

    forbidden_imports = _scan_for_forbidden_imports(build_dir)
    if forbidden_imports:
        details = "; ".join(forbidden_imports)
        raise ExportVerificationError(f"Forbidden imports in export: {details}")
