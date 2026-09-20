"""Headless project creation command using the canonical Project API."""

from __future__ import annotations

import argparse
from pathlib import Path

from expra_engine.core.project import Project, ProjectError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="expra-new")
    parser.add_argument("name")
    parser.add_argument("location", nargs="?", default=".")
    args = parser.parse_args(argv)
    try:
        project = Project.create(args.name, Path(args.location).expanduser() / args.name)
    except (OSError, ProjectError) as exc:
        parser.error(str(exc))
    print(project.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
