"""Standalone entrypoint for the recommended scripted Neon Arena mode."""

from __future__ import annotations

import os
import runpy
from pathlib import Path

os.environ.setdefault("EXPRA_NEON_MODE", "scripted")
runpy.run_path(str(Path(__file__).with_name("__main__.py")), run_name="__main__")
