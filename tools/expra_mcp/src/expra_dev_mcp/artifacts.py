"""Run/artifact management: run_id generation and writing render_snapshot's
PNG bytes and captured diagnostic records under the configured artifact/
diagnostics directories -- never scattered into project folders (spec).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any


def new_run_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:8]}"


def write_snapshot_artifact(artifacts_dir: Path, run_id: str, png_bytes: bytes) -> tuple[Path, str]:
    """Write the PNG under ``<artifacts_dir>/<run_id>/snapshot.png``.

    Returns ``(path, sha256_hex)``.
    """

    run_dir = artifacts_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "snapshot.png"
    path.write_bytes(png_bytes)
    digest = hashlib.sha256(png_bytes).hexdigest()
    return path, digest


def write_diagnostics_records(diagnostics_dir: Path, run_id: str, records: list[dict[str, Any]]) -> Path:
    """Write raw captured log records for later ``diagnostics_analyze``
    aggregation, under ``<diagnostics_dir>/<run_id>/raw_records.json``.
    """

    run_dir = diagnostics_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "raw_records.json"
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return path


def read_diagnostics_records(diagnostics_dir: Path, run_id: str) -> list[dict[str, Any]]:
    path = diagnostics_dir / run_id / "raw_records.json"
    if not path.is_file():
        raise FileNotFoundError(f"no diagnostics captured for run_id={run_id!r} (expected {path})")
    return json.loads(path.read_text(encoding="utf-8"))
