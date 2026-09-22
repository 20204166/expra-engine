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

python_usable() {
    local candidate="$1"
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) and sys.prefix == sys.base_prefix else 1)' \
        >/dev/null 2>&1
}

# User mode: always install into an isolated uv-managed venv — avoids PEP 668
# externally-managed-environment errors and pip-less venv problems.
# System mode: requires a usable system Python 3.12+ and sudo.
if [[ "$mode" == "system" ]]; then
    py=""
    if [[ -n "${EXPRA_SYSTEM_PYTHON:-}" ]]; then
        py="$EXPRA_SYSTEM_PYTHON"
        python_usable "$py" || { echo "ERROR: EXPRA_SYSTEM_PYTHON must be Python 3.12+ outside a virtual environment" >&2; exit 1; }
    elif command -v python3 >/dev/null 2>&1 && python_usable "$(command -v python3)"; then
        py="$(command -v python3)"
    fi
    [[ -n "$py" ]] || { echo "ERROR: --system requires an existing Python 3.12+ interpreter" >&2; exit 1; }
    command -v sudo >/dev/null 2>&1 || { echo "sudo is required for --system" >&2; exit 1; }
    sudo -H "$py" -m pip install --upgrade --upgrade-strategy eager "$wheel"
    bin_dir="$($py -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"
else
    uv="$(command -v uv || true)"
    if [[ -z "$uv" ]]; then
        command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required to bootstrap uv" >&2; exit 1; }
        uv_dir="$tmp/uv-bin"
        mkdir -p "$uv_dir"
        curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
            https://astral.sh/uv/install.sh -o "$tmp/uv-install.sh"
        UV_INSTALL_DIR="$uv_dir" sh "$tmp/uv-install.sh" >/dev/null
        uv="$uv_dir/uv"
    fi
    venv_dir="${EXPRA_ENGINE_VENV:-$HOME/.local/share/expra-engine}"
    "$uv" venv --python 3.12 "$venv_dir" >/dev/null 2>&1 || "$uv" venv "$venv_dir" >/dev/null
    "$uv" pip install --python "$venv_dir/bin/python" --upgrade "$wheel" >/dev/null
    py="$venv_dir/bin/python"
    bin_dir="$venv_dir/bin"
fi

expected_version="${wheel_name#expra_engine-}"
expected_version="${expected_version%-py3-none-any.whl}"
installed_version="$($py -c 'import importlib.metadata as m; print(m.version("expra-engine"))')"
[[ "$installed_version" == "$expected_version" ]] || {
    echo "ERROR: installed $installed_version, expected $expected_version" >&2
    exit 1
}
echo "Installed verified Expra $installed_version. Run: $bin_dir/expra-editor"
