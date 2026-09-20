"""CLI entry point: expra export <project> --target windows|linux

Usage:
    python -m expra_engine.export.cli my_game/ --target windows
    expra export my_game/ --target linux --game-version 1.2.0
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from expra_engine.core.project import Project, ProjectError
from expra_engine.export.events import ExportProgressEvent
from expra_engine.export.exporter import ExportError, GameExporter
from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch, RuntimeProfile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expra export",
        description="Package a game built with Expra Engine for distribution.",
    )
    parser.add_argument("project", type=Path, help="Game project directory")
    parser.add_argument(
        "--target",
        choices=["windows", "linux"],
        required=True,
        help="Target platform",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <project>/builds)",
    )
    parser.add_argument("--game-name", default=None, help="Game name (default: project dir name)")
    parser.add_argument("--game-version", default=None, metavar="VERSION")
    parser.add_argument("--python-version", default="3.12.4", metavar="X.Y.Z")
    parser.add_argument("--arch", choices=["amd64", "arm64"], default="amd64")
    parser.add_argument(
        "--runtime-profile",
        choices=[profile.value for profile in RuntimeProfile],
        default=RuntimeProfile.NONE.value,
        help="Explicit runtime profile (pygame stages the runtime-only engine)",
    )
    parser.add_argument(
        "--entry-point",
        default=None,
        help="Entry point relative to project dir",
    )
    parser.add_argument(
        "--no-bytecode",
        action="store_true",
        help="Skip bytecode compilation (ship .py source)",
    )
    parser.add_argument(
        "--no-debug-launcher",
        action="store_true",
        help="Do not generate a debug launcher",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_dir = args.project.resolve()
    output_dir = (args.output or project_dir / "builds").resolve()
    game_name = args.game_name or project_dir.name
    try:
        project = Project.load(project_dir)
    except ProjectError:
        project = None
    entry_point = args.entry_point or (project.entry_point if project else "__main__.py")
    game_version = args.game_version or (project.game_version if project else "1.0.0")

    try:
        plan = ExportPlan(
            project_dir=project_dir,
            entry_point=entry_point,
            output_dir=output_dir,
            target=ExportTarget(args.target),
            game_name=game_name,
            game_version=game_version,
            python_version=args.python_version,
            arch=PythonArch(args.arch),
            compile_bytecode=not args.no_bytecode,
            debug_launcher=not args.no_debug_launcher,
            runtime_profile=RuntimeProfile(args.runtime_profile),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    cancel = threading.Event()

    def on_progress(event: ExportProgressEvent) -> None:
        print(f"  [{event.phase.value:<22s}] {event.percent:3d}%  {event.message}")

    exporter = GameExporter()
    try:
        out = exporter.export(plan, cancel=cancel, progress=on_progress)
        print(f"\nExport complete: {out}")
        return 0
    except ExportError as e:
        print(f"\nExport failed: {e}", file=sys.stderr)
        return 1


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
