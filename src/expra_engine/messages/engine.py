"""Human-readable runtime lifecycle diagnostics owned by Engine."""

from __future__ import annotations

from expra_engine.messages._format import bounded_text


def world_lifecycle_failed(phase: str, level_id: str, error_type: str, detail: str) -> str:
    return (
        f"{bounded_text(phase, 48)} {bounded_text(level_id, 120)}: "
        f"{bounded_text(error_type, 80)}: {bounded_text(detail, 160)}"
    )


def runtime_preview_tick_failed(error_type: str, detail: str) -> str:
    return (
        f"[Engine] Runtime preview stopped after {bounded_text(error_type, 80)}: "
        f"{bounded_text(detail, 512)}"
    )
