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

wheel="$($py -c 'from pathlib import Path; import re, sys
dist = Path(sys.argv[1]); requested = sys.argv[2]
pattern = re.compile(r"^expra_engine-(\d+\.\d+\.\d+\.\d+)-py3-none-any\.whl$")
wheels = [(tuple(map(int, m.group(1).split("."))), p) for p in dist.glob("expra_engine-*.whl") if (m := pattern.match(p.name))]
if requested:
    wheels = [item for item in wheels if ".".join(map(str, item[0])) == requested]
if not wheels:
    raise SystemExit("no matching Expra wheel found")
print(max(wheels)[1].resolve())' "$here/dist" "$version")"

echo "Verifying wheel: $(basename "$wheel")"
PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m expra_engine._release verify-wheel "$wheel"

source "$here/scripts/install-common.sh"
install_wheel "$wheel" "$mode"
