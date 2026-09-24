"""Tests for tools/observability_report.py -- the deterministic analyzer for
ObservabilityWatcher snapshot JSON (live captures or tools/perf bench runs).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from observability_report import analyze, analyze_snapshot, main  # noqa: E402


def _write_snapshot(path: Path, metrics: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "session_started_at": 100.0,
                "captured_at": 105.0,
                "duration_seconds": 5.0,
                "metrics": metrics,
            }
        ),
        encoding="utf-8",
    )
    return path


def _metric(
    target: str,
    *,
    count: int = 10,
    successes: int | None = None,
    failures: int = 0,
    coalesced: int = 0,
    stale: int = 0,
    in_flight: int = 0,
    peak_in_flight: int = 1,
    p50: float = 0.005,
    p95: float = 0.010,
    maximum: float = 0.012,
    last_error: str | None = None,
) -> dict[str, object]:
    return {
        "target": target,
        "count": count,
        "successes": count if successes is None else successes,
        "failures": failures,
        "cancellations": 0,
        "coalesced": coalesced,
        "stale": stale,
        "rejected": 0,
        "in_flight": in_flight,
        "peak_in_flight": peak_in_flight,
        "last_error": last_error,
        "events": [],
        "samples": [p50] * count,
        "distribution": {"p50": p50, "p95": p95, "maximum": maximum},
    }


def test_healthy_metric_produces_no_findings(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path / "healthy.json", [_metric("editor.pixelbridge.render")])
    report = analyze_snapshot(snapshot)
    assert report["findings"] == []
    assert report["metrics"][0]["target"] == "editor.pixelbridge.render"


def test_slow_stage_over_60fps_budget_is_flagged_info() -> None:
    metric = _metric("editor.pixelbridge.encode", p95=0.020, maximum=0.022)
    findings = _findings_for(metric)
    assert any(f["code"] == "stage_over_60fps_budget" and f["severity"] == "info" for f in findings)


def test_slow_stage_over_30fps_budget_is_flagged_warning() -> None:
    metric = _metric("editor.pixelbridge.photoimage", p95=0.040, maximum=0.045)
    findings = _findings_for(metric)
    assert any(f["code"] == "stage_over_30fps_budget" and f["severity"] == "warning" for f in findings)


def test_outlier_spike_is_flagged() -> None:
    metric = _metric("editor.pixelbridge.encode", p95=0.005, maximum=0.200)
    findings = _findings_for(metric)
    assert any(f["code"] == "stage_outlier_spike" for f in findings)


def test_failures_are_flagged_error() -> None:
    metric = _metric("ui:render:viewport", failures=2, last_error="RuntimeError")
    findings = _findings_for(metric)
    matching = [f for f in findings if f["code"] == "stage_failures"]
    assert matching and matching[0]["severity"] == "error"
    assert "RuntimeError" in matching[0]["message"]


def test_high_coalesce_ratio_is_flagged() -> None:
    metric = _metric("ui:render:viewport", count=100, successes=5, coalesced=50, stale=10)
    findings = _findings_for(metric)
    assert any(f["code"] == "high_coalesce_ratio" for f in findings)


def test_unclosed_span_at_capture_is_flagged_warning() -> None:
    metric = _metric("editor.pixelbridge.render", in_flight=1)
    findings = _findings_for(metric)
    matching = [f for f in findings if f["code"] == "unclosed_span_at_capture"]
    assert matching and matching[0]["severity"] == "warning"


def test_analyze_aggregates_findings_across_files_deterministically(tmp_path: Path) -> None:
    a = _write_snapshot(tmp_path / "a.json", [_metric("stage.a", p95=0.040, maximum=0.045)])
    b = _write_snapshot(tmp_path / "b.json", [_metric("stage.b", failures=1)])

    result_1 = analyze([str(a), str(b)])
    result_2 = analyze([str(b), str(a)])  # order must not affect the result

    assert result_1 == result_2
    assert result_1["summary"]["files"] == 2
    assert result_1["summary"]["findings"] == {"error": 1, "warning": 1}


def test_missing_file_raises_value_error(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="not found"):
        analyze([str(tmp_path / "does-not-exist.json")])


def test_cli_strict_flag_exits_2_on_warning(tmp_path: Path, capsys) -> None:
    snapshot = _write_snapshot(
        tmp_path / "warn.json", [_metric("editor.pixelbridge.encode", p95=0.040, maximum=0.045)]
    )
    exit_code = main([str(snapshot), "--strict"])
    assert exit_code == 2


def test_cli_json_output_is_valid_json(tmp_path: Path, capsys) -> None:
    snapshot = _write_snapshot(tmp_path / "ok.json", [_metric("editor.pixelbridge.render")])
    exit_code = main([str(snapshot), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "expra-observability-analysis/v1"


def _findings_for(metric: dict[str, object]) -> list[dict[str, str]]:
    from observability_report import _metric_findings

    return _metric_findings(metric)
