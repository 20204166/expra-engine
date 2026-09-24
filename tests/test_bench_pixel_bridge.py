"""Smoke test for tools/perf/bench_pixel_bridge.py -- the permanent,
ObservabilityWatcher-wired replacement for ad hoc pixel-bridge profiling
scripts. Confirms it runs against a real project through the real
EditorPixelRenderer and produces a serialize_observability()-shaped report.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "perf"))

from bench_pixel_bridge import run_benchmark  # noqa: E402


def test_run_benchmark_reports_pixelbridge_stage_timings() -> None:
    pytest.importorskip("pygame")
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("no display for real Tk editor presentation")

    report = json.loads(
        run_benchmark(
            project_path=REPO_ROOT / "examples" / "blacksite_relay",
            scene=None,
            width=320,
            height=180,
            iterations=3,
        )
    )

    targets = {m["target"]: m for m in report["metrics"]}
    for stage in (
        "editor.pixelbridge.render",
        "editor.pixelbridge.encode",
        "editor.pixelbridge.photoimage",
    ):
        assert stage in targets
        assert targets[stage]["count"] == 3
        assert targets[stage]["failures"] == 0
