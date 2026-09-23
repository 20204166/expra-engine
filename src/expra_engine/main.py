"""Entry point for the Expra editor."""

from __future__ import annotations

import logging

from expra_engine.core.engine import Engine
from expra_engine.ui.editor_window import EditorWindow


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    engine = Engine()
    window = EditorWindow(engine)
    try:
        window.run()
    except KeyboardInterrupt:
        window._on_close()


if __name__ == "__main__":
    main()
