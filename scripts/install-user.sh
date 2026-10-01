#!/usr/bin/env bash
# Install the latest local Expra wheel using the shared installer.
# Use --system for a machine-wide install (requires sudo).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="user"
version=""
for arg in "$@"; do
    case "$arg" in
        --system) mode="system" ;;
        --*) echo "Unknown option: $arg" >&2; exit 1 ;;
        *) version="$arg" ;;
    esac
done

if [[ -n "${EXPRA_SYSTEM_PYTHON:-}" ]]; then
    py="$EXPRA_SYSTEM_PYTHON"
elif [[ -x "$here/.venv/bin/python" ]]; then
    py="$($here/.venv/bin/python -c 'import sys; print(sys._base_executable)')"
elif command -v python3 >/dev/null 2>&1; then
    py="$(command -v python3)"
else
    echo "ERROR: no system Python 3 found; set EXPRA_SYSTEM_PYTHON." >&2
    exit 1
fi

wheel_version="$(PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -c 'from pathlib import Path; import sys
from expra_engine._release import _matching_wheels, _format_version
dist = Path(sys.argv[1]); requested = sys.argv[2]
wheels = _matching_wheels(dist)
if requested:
    wheels = [item for item in wheels if _format_version(item[0]) == requested]
if not wheels:
    raise SystemExit("no matching Expra wheel found")
print(_format_version(max(version for version, _path in wheels)))' "$here/dist" "$version")"

for wheel in "$here"/dist/expra_engine-"$wheel_version"-*.whl; do
    echo "Verifying wheel: $(basename "$wheel")"
    PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m expra_engine._release verify-wheel "$wheel"
done

source "$here/scripts/install-common.sh"
wheel="$(select_compatible_wheel "$py" "$here/dist" "$wheel_version")"
install_wheel "$wheel" "$mode"
