"""Compare Python fallback, normal optional-Rust mode, and strict Rust mode.

Build/install the optional extension first with ``maturin develop`` from its
crate directory. Run this script in Expra's project environment; it uses the
canonical RenderFrame visibility contract and records bounded distributions
through the engine's ObservabilityWatcher.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime import render_math
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderFrame,
    RenderItem,
    Transform,
    Viewport,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "python", "hybrid", "rust-only"), default="all")
    parser.add_argument("--entities", type=int, default=1000)
    parser.add_argument("--warmups", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.entities <= 0 or args.warmups < 0 or args.iterations <= 0:
        parser.error("--entities and --iterations must be positive; --warmups cannot be negative")
    return args


def _fixture(entity_count: int) -> tuple[RenderFrame, RenderContext]:
    items = tuple(
        RenderItem(
            f"item-{index}",
            PrimitiveDescriptor("rectangle", (0.8, 0.6)),
            Transform(
                position=(
                    ((index * 37) % 160 - 80) / 4,
                    ((index * 53) % 96 - 48) / 4,
                    0.0,
                ),
                rotation=float(index % 31),
            ),
        )
        for index in range(entity_count)
    )
    frame = RenderFrame(items)
    context = RenderContext(Viewport(0, 0, 800, 480), OrthographicCamera(width=40.0, height=24.0))
    return frame, context


def _visible_python(frame: RenderFrame, context: RenderContext) -> tuple[RenderItem, ...]:
    ordered = frame.ordered_items()
    mask = render_math.python_visible_mask(ordered, context)
    return tuple(item for item, visible in zip(ordered, mask, strict=True) if visible)


def _visible_rust_only(frame: RenderFrame, context: RenderContext) -> tuple[RenderItem, ...]:
    ordered = frame.ordered_items()
    mask = render_math.strict_native_visible_mask(ordered, context)
    return tuple(item for item, visible in zip(ordered, mask, strict=True) if visible)


def _bench_mode(
    name: str,
    operation: Callable[[], tuple[RenderItem, ...]],
    *,
    frame: RenderFrame,
    context: RenderContext,
    warmups: int,
    iterations: int,
    observer: ObservabilityWatcher,
) -> None:
    expected = _visible_python(frame, context)
    for _ in range(warmups):
        actual = operation()
        if tuple(item.key for item in actual) != tuple(item.key for item in expected):
            raise RuntimeError(f"{name} visibility output differs from the Python reference")

    target = f"render_math.benchmark.{name}"
    for _ in range(iterations):
        started = time.perf_counter()
        try:
            actual = operation()
        except Exception as error:
            duration = time.perf_counter() - started
            observer.record(target, duration, outcome="failure", detail=type(error).__name__)
            raise
        duration = time.perf_counter() - started
        if tuple(item.key for item in actual) != tuple(item.key for item in expected):
            observer.record(target, duration, outcome="failure", detail="visibility parity mismatch")
            raise RuntimeError(f"{name} visibility output differs from the Python reference")
        observer.record(target, duration)
        observer.increment(target, "items_per_batch", len(frame.items))
        observer.increment(target, "visible_items", len(actual))
        if name == "python":
            observer.increment(target, "python_reference_batches")
        elif name == "rust-only" or render_math.native_available():
            observer.increment(target, "native_batches")
        else:
            observer.increment(target, "python_fallback_batches")


def main() -> int:
    args = _arguments()
    requested_modes = ("python", "hybrid", "rust-only") if args.mode == "all" else (args.mode,)
    if "rust-only" in requested_modes and not render_math.native_available():
        raise RuntimeError("Rust-only benchmark requires an installed, enabled expra_render_math extension")

    frame, context = _fixture(args.entities)
    observer = ObservabilityWatcher(sample_limit=args.iterations)
    operations: dict[str, Callable[[], tuple[RenderItem, ...]]] = {
        "python": lambda: _visible_python(frame, context),
        "hybrid": lambda: frame.visible_items(context),
        "rust-only": lambda: _visible_rust_only(frame, context),
    }
    for mode in requested_modes:
        _bench_mode(
            mode,
            operations[mode],
            frame=frame,
            context=context,
            warmups=args.warmups,
            iterations=args.iterations,
            observer=observer,
        )

    snapshot = observer.snapshot()
    report = {
        "engine_python": sys.version,
        "platform": platform.platform(),
        "native_extension_available": render_math.native_available(),
        "items": args.entities,
        "warmups": args.warmups,
        "iterations": args.iterations,
        "scope": "warmed ordered RenderFrame visibility selection, including per-call Python packing and PyO3 call; excludes extraction and initial order sort",
        "ordered_item_cache_warmed": True,
        "strict_mode_note": "Rust performs visibility math and strict mode raises on failure; RenderItem ordering and FFI input packing remain Python-owned.",
        "observability": asdict(snapshot),
        "comparison": {
            metric.target.rsplit(".", 1)[-1]: metric.distribution
            for metric in snapshot.metrics
        },
        "unit": "seconds",
    }
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.output is None:
        print(output)
    else:
        args.output.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
