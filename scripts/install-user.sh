#!/usr/bin/env bash
# Install the latest Expra wheel into the user/system Python, never the repo venv.
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

if [[ "$py" == "$here/.venv/bin/python" ]] || \
   "$py" -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)'; then
    echo "ERROR: selected interpreter is inside a virtual environment: $py" >&2
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

expected_version="$($py -c 'import re, sys; print(re.search(r"-(\d+\.\d+\.\d+\.\d+)-", sys.argv[1]).group(1))' "$wheel")"
site_scheme="posix_user"
if [[ "$mode" == "system" ]]; then
    site_scheme="posix_prefix"
fi
site_dir="$($py -c 'import sys, sysconfig; print(sysconfig.get_path("purelib", scheme=sys.argv[1]))' "$site_scheme")"

if [[ "$mode" == "system" ]]; then
    command -v sudo >/dev/null 2>&1 || {
        echo "sudo is required for --system" >&2
        exit 1
    }
fi

run_target_python() {
    if [[ "$mode" == "system" ]]; then
        sudo -H env -u PYTHONPATH "$py" "$@"
    else
        env -u PYTHONPATH "$py" "$@"
    fi
}

remove_stale_metadata() {
    run_target_python - "$site_dir" "$expected_version" <<'PY'
from pathlib import Path
import re
import shutil
import sys

site_dir = Path(sys.argv[1])
expected = sys.argv[2]
pattern = re.compile(r"^expra_engine-\d+\.\d+\.\d+\.\d+\.dist-info$")

for metadata in sorted(site_dir.glob("expra_engine-*.dist-info")):
    if metadata.name == f"expra_engine-{expected}.dist-info":
        continue
    if pattern.fullmatch(metadata.name):
        print(f"Removing stale Expra metadata: {metadata}", file=sys.stderr)
        shutil.rmtree(metadata)

editable_metadata = site_dir / "expra_engine.egg-info"
if editable_metadata.is_dir():
    print(f"Removing stale Expra metadata: {editable_metadata}", file=sys.stderr)
    shutil.rmtree(editable_metadata)
PY
}

echo "Verifying wheel: $(basename "$wheel")"
PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m expra_engine._release verify-wheel "$wheel"

remove_stale_metadata

pip_install() {
    local -a command=("$py" -m pip install --upgrade --upgrade-strategy eager)
    if [[ "$mode" == "user" ]]; then
        command+=(--user)
    else
        command=(sudo -H "$py" -m pip install --upgrade --upgrade-strategy eager)
    fi
    if "${command[@]}" --break-system-packages "$wheel"; then
        return 0
    fi
    "${command[@]}" "$wheel"
}

if [[ "$mode" == "system" ]]; then
    echo "Installing Expra system-wide with $py..."
else
    echo "Installing Expra for the current user with $py (outside the repo venv)..."
fi
pip_install

installed_version="$(run_target_python -c 'import importlib.metadata as m; print(m.version("expra-engine"))')"
[[ "$installed_version" == "$expected_version" ]] || {
    echo "ERROR: installed $installed_version, expected $expected_version" >&2
    exit 1
}

bin_dir="$($py -c 'import sysconfig; print(sysconfig.get_path("scripts", scheme="posix_user"))')"
[[ "$mode" == "system" ]] && bin_dir="$($py -c 'import sysconfig; print(sysconfig.get_path("scripts", scheme="posix_prefix"))')"
echo "Installed Expra $installed_version. Launcher: $bin_dir/expra-editor"
if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
    echo "Add this directory to PATH if needed: $bin_dir"
fi
echo "Run: expra-editor"
