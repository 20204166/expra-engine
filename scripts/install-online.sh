#!/usr/bin/env bash
# Download and install the latest verified Expra wheel from the repository.
set -euo pipefail

common_script=""
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install-common.sh"
    [[ -f "$candidate" ]] && common_script="$candidate"
fi
mode="user"
base="${EXPRA_ENGINE_INSTALL_BASE_URL:-https://github.com/20204166/expra-engine/releases/latest/download}"
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
read -r _ first_path < <(awk 'NF { print $1, $2; exit }' "$tmp/SHA256SUMS")
first_wheel="$(basename "$first_path")"
wheel_pattern='^expra_engine-([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)-[^-]+-[^-]+-[^-]+\.whl$'
[[ "$first_wheel" =~ $wheel_pattern ]] || {
    echo "ERROR: unexpected wheel filename in SHA256SUMS" >&2; exit 1;
}
expected_version="${BASH_REMATCH[1]}"
wheel_count=0
while read -r expected path; do
    [[ -n "${path:-}" ]] || continue
    wheel_name="$(basename "$path")"
    [[ "$wheel_name" =~ $wheel_pattern ]] || {
        echo "ERROR: unexpected wheel filename in SHA256SUMS" >&2; exit 1;
    }
    [[ "${BASH_REMATCH[1]}" == "$expected_version" ]] || continue
    [[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || {
        echo "ERROR: invalid wheel checksum in SHA256SUMS" >&2; exit 1;
    }
    wheel="$tmp/$wheel_name"
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        "$base/$wheel_name" -o "$wheel"
    actual="$(sha256sum "$wheel" | cut -d' ' -f1)"
    [[ "$actual" == "$expected" ]] || {
        echo "ERROR: wheel checksum verification failed for $wheel_name" >&2; exit 1;
    }
    wheel_count=$((wheel_count + 1))
done <"$tmp/SHA256SUMS"
[[ "$wheel_count" -gt 0 ]] || {
    echo "ERROR: no compatible-version wheels were listed in SHA256SUMS" >&2; exit 1;
}

if [[ -z "$common_script" ]]; then
    common_script="$tmp/install-common.sh"
    common_url="https://raw.githubusercontent.com/20204166/expra-engine/v${expected_version}/scripts/install-common.sh"
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        "$common_url" -o "$common_script"
fi
source "$common_script"
py="$(resolve_install_python)"
wheel="$(select_compatible_wheel "$py" "$tmp" "$expected_version")"
install_wheel "$wheel" "$mode"
