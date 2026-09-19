#!/usr/bin/env bash
# Verify an Expra wheel and its committed checksum entry.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
py="${EXPRA_PYTHON:-$here/.venv/bin/python}"
export PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}"
wheel="${1:-$("$py" -c 'from pathlib import Path; import sys
from expra_engine._release import _newest_wheel
print(_newest_wheel(Path(sys.argv[1])).resolve())' "$here/dist")}"
"$py" -m expra_engine._release verify-wheel "$wheel"
expected="$(awk -v wheel="$(basename "$wheel")" '$2 == wheel { print $1 }' "$here/dist/SHA256SUMS")"
actual="$(sha256sum "$wheel" | cut -d' ' -f1)"
[[ -z "$expected" || "$expected" == "$actual" ]] || {
    echo "ERROR: SHA256 mismatch for $(basename "$wheel")" >&2
    exit 1
}
echo "SHA256SUMS OK"
