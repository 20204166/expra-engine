#!/usr/bin/env python3
"""Deterministic analyzer for expra ObservabilityWatcher snapshot JSON.

- Standard library only.
- Same input -> same report (no current time, randomness, or network).
- Accepts one or more snapshot JSON files (from a live EditorWindow capture
  or from tools/perf/bench_pixel_bridge.py -- same shape either way, see
  expra_engine.observability.serialize_observability).
- Projects each metric's own count/successes/failures/distribution verbatim
  -- it never recomputes percentiles or re-derives what the observer already
  computed (same discipline as exp_ui's tools/application_performance_audit.py
  and its "projects observer distributions without recomputing them" test).
- Flags budget/health findings with a severity, the same way
  expra_connect_log_analyzer.py flags protocol findings -- but the findings
  here are frame-budget and coalescing-health checks, not connection/pairing
  ones; the domain differs, the reporting shape does not.

Examples:
    python tools/observability_report.py capture.json
    python tools/observability_report.py bench-before.json bench-after.json --json
    python tools/observability_report.py capture.json --strict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Presentation stages faster than this read as comfortably sustaining 60fps;
# above it we can't promise 60fps for that stage alone (other stages share
# the same 16.7ms budget), and above the 30fps figure a stage is a likely
# visible-stutter contributor on its own. These are frame-budget references,
# not hard failures -- see section 7's "prefer stable 40-50fps over unstable
# 60->20->60->15" guidance this tool exists to give evidence for.
FRAME_BUDGET_60FPS_MS = 16.7
FRAME_BUDGET_30FPS_MS = 33.3

# A presentation target where accumulated "stale" + "coalesced" rejections
# outnumber actual commits by this ratio suggests requests are arriving
# faster than they can be (or need to be) presented -- worth a look, not
# necessarily a bug (coalescing IS the intended latest-frame-wins behavior).
HIGH_COALESCE_RATIO = 3.0


def _load_snapshot(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(data, dict) or "metrics" not in data:
        raise ValueError(f"{path}: not an ObservabilityWatcher snapshot (missing 'metrics')")
    return data


def _metric_findings(metric: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    target = str(metric.get("target", "<unknown>"))
    distribution = metric.get("distribution") or {}
    p95_ms = float(distribution.get("p95", 0.0)) * 1000.0
    max_ms = float(distribution.get("maximum", 0.0)) * 1000.0

    if p95_ms > FRAME_BUDGET_30FPS_MS:
        findings.append(
            {
                "severity": "warning",
                "code": "stage_over_30fps_budget",
                "message": (
                    f"{target}: p95={p95_ms:.2f}ms exceeds the "
                    f"{FRAME_BUDGET_30FPS_MS:.1f}ms (30fps) frame budget on its own."
                ),
            }
        )
    elif p95_ms > FRAME_BUDGET_60FPS_MS:
        findings.append(
            {
                "severity": "info",
                "code": "stage_over_60fps_budget",
                "message": (
                    f"{target}: p95={p95_ms:.2f}ms exceeds the "
                    f"{FRAME_BUDGET_60FPS_MS:.1f}ms (60fps) frame budget on its own."
                ),
            }
        )

    if max_ms > FRAME_BUDGET_30FPS_MS * 2:
        findings.append(
            {
                "severity": "warning",
                "code": "stage_outlier_spike",
                "message": f"{target}: worst observed sample was {max_ms:.2f}ms.",
            }
        )

    failures = int(metric.get("failures", 0))
    if failures:
        findings.append(
            {
                "severity": "error",
                "code": "stage_failures",
                "message": (
                    f"{target}: {failures} failure(s) recorded"
                    + (f" ({metric['last_error']})" if metric.get("last_error") else "")
                    + "."
                ),
            }
        )

    commits = int(metric.get("successes", 0))
    rejections = int(metric.get("coalesced", 0)) + int(metric.get("stale", 0))
    if commits > 0 and rejections > commits * HIGH_COALESCE_RATIO:
        findings.append(
            {
                "severity": "info",
                "code": "high_coalesce_ratio",
                "message": (
                    f"{target}: {rejections} coalesced/stale request(s) against "
                    f"{commits} commit(s) -- requests are arriving well faster than "
                    "they're presented (expected under latest-frame-wins coalescing, "
                    "worth confirming it's not a request storm)."
                ),
            }
        )

    peak_in_flight = int(metric.get("peak_in_flight", 0))
    in_flight = int(metric.get("in_flight", 0))
    if in_flight > 0:
        findings.append(
            {
                "severity": "warning",
                "code": "unclosed_span_at_capture",
                "message": (
                    f"{target}: {in_flight} span(s) still open when the snapshot was "
                    "captured -- a begin() without a matching finish(), or the capture "
                    "happened mid-operation."
                ),
            }
        )
    elif peak_in_flight > 1:
        findings.append(
            {
                "severity": "info",
                "code": "overlapping_spans_observed",
                "message": f"{target}: up to {peak_in_flight} overlapping span(s) observed.",
            }
        )

    return findings


def _projected_metric(metric: dict[str, Any]) -> dict[str, Any]:
    """Project only the fields this report displays -- never re-derive them."""
    distribution = metric.get("distribution") or {}
    return {
        "target": metric.get("target"),
        "count": metric.get("count"),
        "successes": metric.get("successes"),
        "failures": metric.get("failures"),
        "coalesced": metric.get("coalesced"),
        "stale": metric.get("stale"),
        "rejected": metric.get("rejected"),
        "in_flight": metric.get("in_flight"),
        "peak_in_flight": metric.get("peak_in_flight"),
        "p50_ms": round(float(distribution.get("p50", 0.0)) * 1000.0, 3)
        if distribution
        else None,
        "p95_ms": round(float(distribution.get("p95", 0.0)) * 1000.0, 3)
        if distribution
        else None,
        "max_ms": round(float(distribution.get("maximum", 0.0)) * 1000.0, 3)
        if distribution
        else None,
    }


def analyze_snapshot(path: Path) -> dict[str, Any]:
    snapshot = _load_snapshot(path)
    metrics = [m for m in (snapshot.get("metrics") or []) if isinstance(m, dict)]

    findings: list[dict[str, str]] = []
    for metric in sorted(metrics, key=lambda m: str(m.get("target", ""))):
        findings.extend(_metric_findings(metric))

    return {
        "file": path.name,
        "captured_at": snapshot.get("captured_at"),
        "session_started_at": snapshot.get("session_started_at"),
        "duration_seconds": snapshot.get("duration_seconds"),
        "metric_count": len(metrics),
        "metrics": [_projected_metric(m) for m in sorted(metrics, key=lambda m: str(m.get("target", "")))],
        "findings": findings,
    }


def analyze(inputs: list[str]) -> dict[str, Any]:
    paths = sorted({Path(raw).resolve() for raw in inputs}, key=str)
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise ValueError("file(s) not found: " + ", ".join(str(p) for p in missing))

    reports = [analyze_snapshot(path) for path in paths]
    from collections import Counter

    finding_counts: Counter[str] = Counter()
    for report in reports:
        for finding in report["findings"]:
            finding_counts[finding["severity"]] += 1

    return {
        "format": "expra-observability-analysis/v1",
        "summary": {
            "files": len(reports),
            "total_metrics": sum(r["metric_count"] for r in reports),
            "findings": dict(sorted(finding_counts.items())),
        },
        "files": reports,
    }


def _print_text(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("EXPRA OBSERVABILITY ANALYSIS")
    print("=" * 28)
    print(f"Files: {summary['files']}")
    print(f"Metrics: {summary['total_metrics']}")
    finding_bits = [f"{k}={v}" for k, v in summary["findings"].items()]
    print("Findings: " + (", ".join(finding_bits) or "none"))

    for file_report in report["files"]:
        print()
        print(f"FILE: {file_report['file']}")
        if file_report["duration_seconds"] is not None:
            print(f"  Session duration: {file_report['duration_seconds']:.3f}s")
        print(f"  Metrics: {file_report['metric_count']}")
        for metric in file_report["metrics"]:
            print(
                f"    {metric['target']:36s} count={metric['count']:<5} "
                f"p50={metric['p50_ms']}ms p95={metric['p95_ms']}ms max={metric['max_ms']}ms "
                f"failures={metric['failures']} coalesced={metric['coalesced']} stale={metric['stale']}"
            )
        for finding in file_report["findings"]:
            print(f"  [{finding['severity'].upper()}] {finding['code']}: {finding['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="ObservabilityWatcher snapshot JSON file(s)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="exit 2 if warning/error findings are present")
    args = parser.parse_args(argv)

    try:
        report = analyze(args.inputs)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)

    if args.strict:
        findings = report["summary"]["findings"]
        if findings.get("warning", 0) or findings.get("error", 0):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
