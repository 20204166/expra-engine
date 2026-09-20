"""verify_export(): verifies a completed export build. Fails closed."""

from __future__ import annotations

import json
from pathlib import Path

_REQUIRED_MANIFEST_KEYS: frozenset[str] = frozenset({
    "game_name",
    "game_version",
    "engine_version",
    "target",
    "python_version",
    "arch",
    "compile_bytecode",
    "entry_point",
    "build_timestamp",
})


class ExportVerificationError(RuntimeError):
    pass


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
