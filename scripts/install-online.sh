#!/usr/bin/env bash
# Download and install the latest verified Expra wheel from the repository.
set -euo pipefail

mode="user"
base="${EXPRA_ENGINE_INSTALL_BASE_URL:-https://raw.githubusercontent.com/20204166/expra-engine/main/dist}"
for arg in "$@"; do
    case "$arg" in
        --system) mode="system" ;;
        --base-url=*) base="${arg#*=}" ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required" >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "ERROR: sha256sum is required" >&2; exit 1; }
if [[ -n "${EXPRA_SYSTEM_PYTHON:-}" ]]; then
    py="$EXPRA_SYSTEM_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    py="$(command -v python3)"
else
    echo "ERROR: no system Python 3 found; set EXPRA_SYSTEM_PYTHON." >&2
    exit 1
fi
if "$py" -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)'; then
    echo "ERROR: selected interpreter is inside a virtual environment: $py" >&2
    exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "$base/SHA256SUMS" -o "$tmp/SHA256SUMS"
wheel_name="$(awk 'NF { print $2; exit }' "$tmp/SHA256SUMS" | xargs -n1 basename)"
[[ "$wheel_name" =~ ^expra_engine-[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-py3-none-any\.whl$ ]] || {
    echo "ERROR: unexpected wheel filename in SHA256SUMS" >&2; exit 1;
}
wheel="$tmp/$wheel_name"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "$base/$wheel_name" -o "$wheel"
expected="$(awk -v wheel="$wheel_name" '$2 == wheel || $2 == "dist/" wheel { print $1; exit }' "$tmp/SHA256SUMS")"
actual="$(sha256sum "$wheel" | cut -d' ' -f1)"
[[ "$expected" =~ ^[0-9a-fA-F]{64}$ && "$actual" == "$expected" ]] || {
    echo "ERROR: wheel checksum verification failed" >&2; exit 1;
}

if [[ "$mode" == "system" ]]; then
    command -v sudo >/dev/null 2>&1 || { echo "sudo is required for --system" >&2; exit 1; }
    sudo -H "$py" -m pip install --upgrade --upgrade-strategy eager "$wheel"
else
    "$py" -m pip install --user --upgrade --upgrade-strategy eager "$wheel"
fi

expected_version="${wheel_name#expra_engine-}"
expected_version="${expected_version%-py3-none-any.whl}"
installed_version="$($py -c 'import importlib.metadata as m; print(m.version("expra-engine"))')"
[[ "$installed_version" == "$expected_version" ]] || {
    echo "ERROR: installed $installed_version, expected $expected_version" >&2
    exit 1
}
echo "Installed verified Expra $installed_version. Run: expra-editor"
