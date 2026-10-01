#!/usr/bin/env bash
# Build the Expra wheel into dist/ without installing it.
#
# The release helper compares source inputs with the newest local wheel,
# automatically bumps the Expra version when needed, refreshes SHA256SUMS, and
# verifies the resulting wheel. Override the bump with EXPRA_VERSION_BUMP.
set -euo pipefail
shopt -s nullglob

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bump="${EXPRA_VERSION_BUMP:-auto}"
rust_mode="${EXPRA_BUILD_RUST:-auto}"

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
wheel_stage=""
artifact_backup=""
artifact_backup_ready=0
artifact_backup_had_sha=0
version=""
export PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}"

case "$rust_mode" in
    auto)
        if command -v cargo >/dev/null 2>&1; then
            rust_mode=1
        else
            rust_mode=0
            echo "note: Cargo unavailable; building the universal Python fallback wheel only"
        fi
        ;;
    0|1) ;;
    *) echo "ERROR: EXPRA_BUILD_RUST must be auto, 0, or 1." >&2; exit 1 ;;
esac
if [[ "$rust_mode" == 1 ]] && ! command -v cargo >/dev/null 2>&1; then
    echo "ERROR: EXPRA_BUILD_RUST=1 requires Cargo on PATH." >&2
    exit 1
fi

cleanup() {
    if [[ "$built_ok" -ne 1 ]]; then
        cp "$version_backup" "$here/src/expra_engine/_version.py"
        echo "note: restored src/expra_engine/_version.py after failed build" >&2
        if [[ "$artifact_backup_ready" -eq 1 ]]; then
            current_wheels=("$here"/dist/expra_engine-"$version"-*.whl)
            if [[ "${#current_wheels[@]}" -gt 0 ]]; then
                rm -f "${current_wheels[@]}"
            fi
            previous_wheels=("$artifact_backup"/expra_engine-"$version"-*.whl)
            if [[ "${#previous_wheels[@]}" -gt 0 ]]; then
                cp -a "${previous_wheels[@]}" "$here/dist/"
            fi
            if [[ "$artifact_backup_had_sha" -eq 1 ]]; then
                cp "$artifact_backup/SHA256SUMS" "$here/dist/SHA256SUMS"
            else
                rm -f "$here/dist/SHA256SUMS"
            fi
            echo "note: restored previous wheel artifacts after failed publication" >&2
        fi
    fi
    if [[ -n "$wheel_stage" && -d "$wheel_stage" ]]; then
        rm -rf "$wheel_stage"
    fi
    if [[ -n "$artifact_backup" && -d "$artifact_backup" ]]; then
        rm -rf "$artifact_backup"
    fi
    rm -f "$version_backup"
}
trap cleanup EXIT

echo "Preparing Expra build inputs and version..."
"$py" -m expra_engine._release prepare-build \
    --package-dir "$here" \
    --bump "$bump"

wheel_stage="$(mktemp -d "$here/.wheel-build.XXXXXX")"
version="$($py -c 'from pathlib import Path; import sys
from expra_engine._release import read_current_version
print(read_current_version(Path(sys.argv[1])))' "$here")"

# setuptools leaves removed modules in build/lib; never let an older build tree
# reintroduce deleted editor frontends into a fresh wheel.
rm -rf "$here/build"

echo "Building universal Python fallback wheel..."
EXPRA_BUILD_RUST=0 "$py" -m build --wheel --outdir "$wheel_stage" "$here"

if [[ "$rust_mode" == 1 ]]; then
    rm -rf "$here/build"
    echo "Building platform-specific Expra wheel with the Rust accelerator..."
    EXPRA_BUILD_RUST=1 "$py" -m build --wheel --outdir "$wheel_stage" "$here"
fi

staged_wheels=("$wheel_stage"/expra_engine-"$version"-*.whl)
if [[ "${#staged_wheels[@]}" -eq 0 ]]; then
    echo "ERROR: wheel build produced no Expra artifacts for $version." >&2
    exit 1
fi
for staged_wheel in "${staged_wheels[@]}"; do
    "$py" -m expra_engine._release verify-wheel "$staged_wheel"
done
"$py" -c 'from pathlib import Path; import sys
from expra_engine._release import rewrite_sha256sums
rewrite_sha256sums(Path(sys.argv[1]))' "$wheel_stage"

mkdir -p "$here/dist"
artifact_backup="$(mktemp -d "$here/.wheel-artifacts.XXXXXX")"
current_wheels=("$here"/dist/expra_engine-"$version"-*.whl)
if [[ "${#current_wheels[@]}" -gt 0 ]]; then
    cp -a "${current_wheels[@]}" "$artifact_backup/"
fi
if [[ -f "$here/dist/SHA256SUMS" ]]; then
    cp "$here/dist/SHA256SUMS" "$artifact_backup/SHA256SUMS"
    artifact_backup_had_sha=1
fi
artifact_backup_ready=1
if [[ "${#current_wheels[@]}" -gt 0 ]]; then
    rm -f "${current_wheels[@]}"
fi
mv "${staged_wheels[@]}" "$here/dist/"
cp "$wheel_stage/SHA256SUMS" "$here/dist/SHA256SUMS"

wheel="$($py -c 'from pathlib import Path; import sys
from expra_engine._release import _newest_wheel
print(_newest_wheel(Path(sys.argv[1])).resolve())' "$here/dist")"
"$py" -m expra_engine._release sync-artifacts --package-dir "$here"
version="$($py -c 'from pathlib import Path; import sys
from expra_engine._release import _wheel_version
print(_wheel_version(Path(sys.argv[1])))' "$wheel")"
for built_wheel in "$here"/dist/expra_engine-"$version"-*.whl; do
    "$py" -m expra_engine._release verify-wheel "$built_wheel"
done

built_ok=1
echo "Built and verified: $wheel"
