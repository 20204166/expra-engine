#!/usr/bin/env python3
"""Benchmark the editor's pixel-render bridge, wired to ObservabilityWatcher.

Renders a project's active scene through the REAL EditorPixelRenderer (the
same code path the live editor uses) for a fixed number of iterations,
recording per-stage timing through the same ObservabilityWatcher primitive
UICoordinator uses for ui:render:* commit timing (see
expra_engine.observability). The result is serialized with
serialize_observability() -- the identical shape a live EditorWindow capture
would produce (see EditorWindow._observer) -- so
tools/observability_report.py can analyze either a real capture or a bench
run without caring which one it is.

This replaces ad hoc one-off profiling scripts with a permanent, rerunnable
regression tool: run it before and after a change to the pixel bridge and
diff the two JSON reports.

Usage:
    .venv/bin/python tools/perf/bench_pixel_bridge.py
    .venv/bin/python tools/perf/bench_pixel_bridge.py --project examples/space_pong --iterations 200
    .venv/bin/python tools/perf/bench_pixel_bridge.py --output bench-report.json
"""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default="examples/blacksite_relay",
        help="project directory, relative to the repo root (default: %(default)s)",
    )
    parser.add_argument("--scene", default=None, help="scene path relative to the project")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path, default=None, help="write JSON here instead of stdout")
    return parser


def run_benchmark(
    *,
    project_path: Path,
    scene: str | None,
    width: int,
    height: int,
    iterations: int,
) -> str:
    """Render ``iterations`` frames and return a serialize_observability() JSON string."""
    from expra_engine.core.project import Project
    from expra_engine.observability import ObservabilityWatcher, serialize_observability
    from expra_engine.runtime.render_extractor import extract_render_frame
    from expra_engine.ui.editor_pixel_renderer import EditorPixelRenderer
    from expra_engine.ui.viewport_camera import ViewportCamera

    project = Project.load(project_path)
    active_scene = project.load_scene(scene)
    resource_service = project.resource_service()
    frame = extract_render_frame(active_scene)

    root = tk.Tk()
    root.withdraw()
    try:
        observer = ObservabilityWatcher()
        renderer = EditorPixelRenderer(resource_service, observer=observer)
        camera = ViewportCamera((width, height))

        for _ in range(iterations):
            image = renderer.render(frame, camera, width, height, root)
            if image is None:
                raise RuntimeError(
                    "EditorPixelRenderer.render() returned None -- backend failure, "
                    "see logged diagnostics"
                )
        return serialize_observability(observer)
    finally:
        root.destroy()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_path = (REPO_ROOT / args.project).resolve()
    if not project_path.exists():
        print(f"error: project not found: {project_path}", file=sys.stderr)
        return 1

    try:
        report = run_benchmark(
            project_path=project_path,
            scene=args.scene,
            width=args.width,
            height=args.height,
            iterations=args.iterations,
        )
    except tk.TclError as exc:
        print(f"error: no Tk display available: {exc}", file=sys.stderr)
        return 1

    if args.output is None:
        print(report)
    else:
        args.output.write_text(report + "\n", encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
