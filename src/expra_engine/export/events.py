"""Export progress events — injected into GameExporter, no tkinter dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExportPhase(StrEnum):
    PLANNING = "planning"
    COLLECTING_ASSETS = "collecting_assets"
    COMPILING_BYTECODE = "compiling_bytecode"
    COPYING_RUNTIME = "copying_runtime"
    RESOLVING_DEPS = "resolving_deps"
    WRITING_MANIFESTS = "writing_manifests"
    VERIFYING = "verifying"
    PROMOTING = "promoting"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class ExportProgressEvent:
    """Single progress notification emitted during export."""

    phase: ExportPhase
    message: str
    percent: int  # 0-100 inclusive
