#!/usr/bin/env bash
# Build or install an Expra wheel in a clean venv and verify the editor entry point.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${EXPRA_PYTHON:-}" ]]; then
    py="$EXPRA_PYTHON"
elif [[ -x "$here/.venv/bin/python" ]]; then
    py="$here/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    py="$(command -v python3)"
else
    echo "ERROR: no Python 3 interpreter found; set EXPRA_PYTHON." >&2
    exit 1
fi

export PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

wheel_input="${1:-}"
if [[ -n "$wheel_input" ]]; then
    [[ -f "$wheel_input" ]] || {
        echo "ERROR: wheel does not exist: $wheel_input" >&2
        exit 1
    }
    wheel="$(readlink -f "$wheel_input")"
else
    echo "Building wheel for installed-editor smoke check..."
    "$py" -m build --wheel --outdir "$tmp/dist" "$here"
    wheel="$($py -c 'from pathlib import Path; import sys
from expra_engine._release import _newest_wheel
print(_newest_wheel(Path(sys.argv[1])).resolve())' "$tmp/dist")"
fi

"$py" -m expra_engine._release verify-wheel "$wheel"

venv="$tmp/venv"
"$py" -m venv "$venv"
venv_python="$venv/bin/python"
PATH="$venv/bin:$PATH" env -u PYTHONPATH "$venv_python" -m pip install \
    --disable-pip-version-check "$wheel"

PATH="$venv/bin:$PATH" env -u PYTHONPATH "$venv_python" - "$wheel" <<'PY'
import importlib.metadata as metadata
import shutil
import sys
from pathlib import Path

wheel = Path(sys.argv[1])
distribution = metadata.distribution("expra-engine")
requires = distribution.requires or []
assert any(requirement.startswith("pygame>=2.6") for requirement in requires), requires
assert not any('extra == "runtime-pygame"' in requirement for requirement in requires), requires

import pygame
from expra_engine.main import main
from expra_engine.ui.editor_pixel_renderer import EditorPixelRenderer

launcher = shutil.which("expra-editor")
assert launcher is not None
assert main is not None
assert EditorPixelRenderer is not None
print(f"installed editor smoke passed: {wheel.name}; pygame={pygame.version.ver}; launcher={launcher}")
PY
