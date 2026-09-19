#!/usr/bin/env bash
# Build the Expra wheel into dist/ without installing it.
#
# The release helper compares source inputs with the newest local wheel,
# automatically bumps the Expra version when needed, refreshes SHA256SUMS, and
# verifies the resulting wheel. Override the bump with EXPRA_VERSION_BUMP.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bump="${EXPRA_VERSION_BUMP:-auto}"

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

version_backup="$(mktemp)"
cp "$here/src/expra_engine/_version.py" "$version_backup"
built_ok=0
export PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}"

cleanup() {
    if [[ "$built_ok" -ne 1 ]]; then
        cp "$version_backup" "$here/src/expra_engine/_version.py"
        echo "note: restored src/expra_engine/_version.py after failed build" >&2
    fi
    rm -f "$version_backup"
}
trap cleanup EXIT

echo "Preparing Expra build inputs and version..."
"$py" -m expra_engine._release prepare-build \
    --package-dir "$here" \
    --bump "$bump"

echo "Building Expra wheel..."
"$py" -m build --wheel --outdir "$here/dist" "$here"

wheel="$($py -c 'from pathlib import Path; import sys
from expra_engine._release import _newest_wheel
print(_newest_wheel(Path(sys.argv[1])).resolve())' "$here/dist")"
"$py" -m expra_engine._release sync-artifacts --package-dir "$here"
"$py" -m expra_engine._release verify-wheel "$wheel"

built_ok=1
echo "Built and verified: $wheel"
