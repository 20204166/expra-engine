#!/usr/bin/env bash
# Download and install the latest verified Expra wheel from the repository.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

source "$here/scripts/install-common.sh"
install_wheel "$wheel" "$mode"
