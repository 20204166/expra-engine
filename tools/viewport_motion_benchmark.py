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
from expra_engine.observability import ObservabilityWatcher, summarize_samples
from expra_engine.runtime.visual_components import PrimitiveComponent
from tests.test_qt_viewport import QtHarness


def _scene(entity_count: int) -> Scene:
    scene = Scene(f"Viewport motion benchmark ({entity_count})")
    for index in range(entity_count):
        if entity_count <= 1000:
            x = float(index % 50)
            y = float(index // 50)
        else:
            x = float(index % 200 - 100)
            y = float(index // 200 - 25)
        entity = scene.create_entity(f"item-{index}")
        entity.add_component(TransformComponent(x=x, y=y))
        entity.add_component(PrimitiveComponent("rectangle"))
    return scene


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entities", type=int, default=1000)
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--gesture", choices=("pan", "zoom"), default="pan")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.entities <= 0 or args.events <= 0 or args.warmups < 0:
        parser.error("--entities/--events must be positive and --warmups non-negative")
    return args


def _summary_ms(samples: tuple[float, ...]) -> dict[str, int | float]:
    return {
        key: value if key == "outliers" else value * 1000
        for key, value in summarize_samples(samples).items()
    }


def main() -> int:
    args = _arguments()
    scene = _scene(args.entities)
    observer = ObservabilityWatcher(sample_limit=max(args.events, args.warmups, 1))
    harness = QtHarness(observer=observer)
    samples: list[float] = []
    try:
        started = time.perf_counter()
        harness.panel.render(scene)
        harness.pump()
        initial_render_seconds = time.perf_counter() - started
        canvas_items = len(harness.canvas.find_all())
        observer.reset()

        if args.gesture == "pan":
            harness.press(200, 200, button=2)
            for index in range(args.warmups):
                harness.motion(201 + index, 201 + index, button=2)
            for index in range(args.events):
                started = time.perf_counter()
                harness.motion(201 + args.warmups + index, 201 + args.warmups + index, button=2)
                samples.append(time.perf_counter() - started)
            harness.release(201 + args.warmups + args.events, 201 + args.warmups + args.events, button=2)
        else:
            for _ in range(args.warmups):
                harness.wheel(200, 200, 120)
            for index in range(args.events):
                started = time.perf_counter()
                harness.wheel(200, 200, 120 if index % 2 == 0 else -120)
                samples.append(time.perf_counter() - started)

        snapshot = observer.snapshot()
        metrics = {metric.target: metric for metric in snapshot.metrics}
        extract_metric = metrics.get("render:extract")
        plan_metric = metrics.get("render:plan")
        report = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "gesture": args.gesture,
            "entities": args.entities,
            "events": args.events,
            "warmups": args.warmups,
            "canvas_items_after_initial_render": canvas_items,
            "initial_render_ms": initial_render_seconds * 1000,
            "event_wall_ms": _summary_ms(tuple(samples)),
            "extract_count": extract_metric.count if extract_metric is not None else 0,
            "plan_count": plan_metric.count if plan_metric is not None else 0,
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
