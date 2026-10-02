"""Measure real Qt viewport pan/zoom wall time and shared renderer observations.

Run from the Expra checkout in its development environment. Input is delivered
through the same QTest/QMouseEvent/QWheelEvent helper as ``tests/test_qt_viewport``.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.core.spatial_index import SpatialIndex2D
from expra_engine.observability import ObservabilityWatcher, summarize_samples
from expra_engine.runtime.visual_components import PrimitiveComponent
from tests.test_qt_viewport import QtHarness


def _scene(entity_count: int, marker_ratio: float = 0.0) -> Scene:
    scene = Scene(f"Viewport motion benchmark ({entity_count})")
    marker_count = round(entity_count * marker_ratio)
    for index in range(entity_count):
        if entity_count <= 1000:
            x = float(index % 50)
            y = float(index // 50)
        else:
            x = float(index % 200 - 100)
            y = float(index // 200 - 25)
        entity = scene.create_entity(f"item-{index}")
        entity.add_component(TransformComponent(x=x, y=y))
        if index >= marker_count:
            entity.add_component(PrimitiveComponent("rectangle"))
    return scene


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entities", type=int, default=1000)
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--gesture", choices=("pan", "zoom"), default="pan")
    parser.add_argument(
        "--marker-ratio",
        type=float,
        default=0.0,
        help="fraction of entities without visuals, therefore shown as editor markers",
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    if (
        args.entities <= 0
        or args.events <= 0
        or args.warmups < 0
        or not 0.0 <= args.marker_ratio <= 1.0
    ):
        parser.error(
            "--entities/--events must be positive, --warmups non-negative, "
            "and --marker-ratio must be in [0, 1]"
        )
    return args


def _summary_ms(samples: tuple[float, ...]) -> dict[str, int | float]:
    if not samples:
        return {}
    return {
        key: value if key == "outliers" else value * 1000
        for key, value in summarize_samples(samples).items()
    }


def _operation_summary(samples: list[dict[str, int]]) -> dict[str, dict[str, int | float]]:
    keys = (
        "created",
        "coordinate_updates",
        "style_updates",
        "deleted",
        "z_updates",
        "world_group_transforms",
        "touched",
    )
    result: dict[str, dict[str, int | float]] = {}
    for key in keys:
        values = tuple(float(sample.get(key, 0)) for sample in samples)
        summary = summarize_samples(values)
        result[key] = {
            "total": int(sum(values)),
            "p50_per_event": summary["p50"],
            "p95_per_event": summary["p95"],
            "max_per_event": summary["maximum"],
        }
    return result


def _spatial_index_summary(index: SpatialIndex2D[int] | None) -> dict[str, int]:
    if index is None:
        return {"entries": 0, "cells": 0, "cell_references": 0, "overflow_entries": 0}
    return {
        "entries": index.entry_count,
        "cells": index.cell_count,
        "cell_references": index.cell_reference_count,
        "overflow_entries": index.overflow_entry_count,
    }


def main() -> int:
    args = _arguments()
    scene = _scene(args.entities, args.marker_ratio)
    observer = ObservabilityWatcher(sample_limit=max(args.events, args.warmups, 1))
    harness = QtHarness(observer=observer)
    samples: list[float] = []
    operation_samples: list[dict[str, int]] = []
    try:
        started = time.perf_counter()
        harness.panel.render(scene)
        harness.pump()
        initial_render_seconds = time.perf_counter() - started
        canvas_items = len(harness.canvas.find_all())
        qgraphics_items = len(harness.canvas._qscene.items())
        harness.canvas.start_operation_metrics()

        if args.gesture == "pan":
            harness.press(200, 200, button=2)
            for index in range(args.warmups):
                harness.motion(201 + index, 201 + index, button=2)
            harness.canvas.take_operation_metrics()
            observer.reset()
            for index in range(args.events):
                started = time.perf_counter()
                harness.motion(201 + args.warmups + index, 201 + args.warmups + index, button=2)
                samples.append(time.perf_counter() - started)
                operation_samples.append(harness.canvas.take_operation_metrics())
            harness.release(201 + args.warmups + args.events, 201 + args.warmups + args.events, button=2)
        else:
            for _ in range(args.warmups):
                harness.wheel(200, 200, 120)
            harness.canvas.take_operation_metrics()
            observer.reset()
            for index in range(args.events):
                started = time.perf_counter()
                harness.wheel(200, 200, 120 if index % 2 == 0 else -120)
                samples.append(time.perf_counter() - started)
                operation_samples.append(harness.canvas.take_operation_metrics())

        snapshot = observer.snapshot()
        metrics = {metric.target: metric for metric in snapshot.metrics}
        extract_metric = metrics.get("render:extract")
        plan_metric = metrics.get("render:plan")
        marker_metric = metrics.get("editor.viewport.markers")
        marker_frame = harness.panel._marker_frame
        render_index_cache = harness.panel._target.frame._spatial_index_cache
        report = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "gesture": args.gesture,
            "entities": args.entities,
            "marker_entities": round(args.entities * args.marker_ratio),
            "marker_ratio": args.marker_ratio,
            "events": args.events,
            "warmups": args.warmups,
            "canvas_items_after_initial_render": canvas_items,
            "canvas_items_after_events": len(harness.canvas._items),
            "qgraphics_scene_items_after_initial_render": qgraphics_items,
            "qgraphics_scene_items_after_events": len(harness.canvas._qscene.items()),
            "initial_render_ms": initial_render_seconds * 1000,
            "event_wall_ms": _summary_ms(tuple(samples)),
            "qt_item_operations": _operation_summary(operation_samples),
            "render_items_total": len(harness.panel._target.frame.items),
            "render_items_visible_after_last_pan": len(harness.panel._target.items),
            "marker_candidates_total": len(marker_frame.markers) if marker_frame is not None else 0,
            "marker_entries_active_after_last_pan": len(harness.panel._marker_entries),
            "spatial_index": {
                "render_world": _spatial_index_summary(
                    render_index_cache.index if render_index_cache is not None else None
                ),
                "editor_markers": (
                    _spatial_index_summary(marker_frame.index)
                    if marker_frame is not None
                    else _spatial_index_summary(None)
                ),
                "colliders": _spatial_index_summary(
                    harness.panel._target.collider_spatial_index
                ),
            },
            "extract_count": extract_metric.count if extract_metric is not None else 0,
            "plan_count": plan_metric.count if plan_metric is not None else 0,
            "marker_candidate_visits": (
                dict(marker_metric.counters) if marker_metric is not None else {}
            ),
            "observability": {
                target: {
                    "count": metric.count,
                    "failures": metric.failures,
                    "distribution_ms": _summary_ms(metric.samples),
                    "counters": dict(metric.counters),
                }
                for target, metric in metrics.items()
            },
        }
    finally:
        harness.close()

    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
