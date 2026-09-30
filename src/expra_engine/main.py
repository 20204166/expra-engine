"""Entry point for the Expra editor (PySide6 / Qt)."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from expra_engine.core.engine import Engine


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    argparse.ArgumentParser(description="Expra editor").parse_args(argv)

    try:
        from expra_engine.editor.qt.app import run_qt_editor
    except ImportError as exc:
        raise SystemExit(
            "PySide6 is a required dependency of the Expra editor but is not installed "
            "(the installation is incomplete).  Reinstall Expra, or install it with:  "
            "pip install PySide6"
        ) from exc
    raise SystemExit(run_qt_editor(Engine()))


if __name__ == "__main__":
    main()
