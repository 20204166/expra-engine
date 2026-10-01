#!/usr/bin/env bash
# Shared wheel installer: per-user venv by default, elevated system install with --system.
set -euo pipefail

resolve_install_python() {
    if [[ -n "${EXPRA_SYSTEM_PYTHON:-}" ]]; then
        printf '%s\n' "$EXPRA_SYSTEM_PYTHON"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    else
        echo "ERROR: no Python 3 interpreter found; set EXPRA_SYSTEM_PYTHON." >&2
        return 1
    fi
}

select_compatible_wheel() {
    local py="$1"
    local wheelhouse="$2"
    local version="$3"
    "$py" - "$wheelhouse" "$version" <<'PY'
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

wheelhouse = Path(sys.argv[1]).resolve()
version = sys.argv[2]
with tempfile.NamedTemporaryFile(prefix=".expra-wheel-select-", suffix=".json", dir=wheelhouse, delete=False) as stream:
    report_path = Path(stream.name)
try:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--no-deps",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "--report",
            str(report_path),
            f"expra-engine=={version}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    install = json.loads(report_path.read_text(encoding="utf-8"))["install"]
    if len(install) != 1:
        raise SystemExit("pip did not select exactly one local Expra wheel")
    url = urlparse(install[0]["download_info"]["url"])
    if url.scheme != "file":
        raise SystemExit("pip selected a non-local Expra wheel")
    wheel = Path(unquote(url.path)).resolve()
    wheel.relative_to(wheelhouse)
    if not re.match(rf"^expra_engine-{re.escape(version)}-[^-]+-[^-]+-[^-]+\.whl$", wheel.name):
        raise SystemExit("pip selected a wheel with an unexpected Expra version")
    print(wheel)
finally:
    report_path.unlink(missing_ok=True)
PY
}

install_wheel() {
    local wheel="$1"
    local mode="${2:-user}"
    local wheel_name
    local expected_version
    wheel_name="$(basename "$wheel")"
    if [[ "$wheel_name" =~ ^expra_engine-([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)-[^-]+-[^-]+-[^-]+\.whl$ ]]; then
        expected_version="${BASH_REMATCH[1]}"
    else
        echo "ERROR: unexpected Expra wheel filename: $wheel_name" >&2
        return 1
    fi

    [[ "$mode" == "user" || "$mode" == "system" ]] || {
        echo "ERROR: unsupported install mode: $mode" >&2
        return 1
    }

    local base_py
    base_py="$(resolve_install_python)"

    if "$base_py" -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' \
        >/dev/null 2>&1 && [[ "$mode" == "system" ]]; then
        echo "ERROR: --system requires a Python outside a virtual environment: $base_py" >&2
        return 1
    fi

    local py="$base_py"
    local bin_dir=""

    if [[ "$mode" == "user" ]]; then
        local root="${EXPRA_ENGINE_INSTALL_ROOT:-$HOME/.local/share/expra-engine}"
        local version_dir="$root/versions/$expected_version"
        if [[ ! -x "$version_dir/bin/python" ]]; then
            mkdir -p "$root/versions"
            "$base_py" -m venv "$version_dir"
        fi
        env -u PYTHONPATH "$version_dir/bin/python" -m pip install \
            --upgrade --upgrade-strategy eager "$wheel"
        printf '%s\n' "$version_dir" >"$root/current"
        py="$version_dir/bin/python"
        bin_dir="$version_dir/bin"
    else
        command -v sudo >/dev/null 2>&1 || {
            echo "ERROR: sudo is required for --system" >&2
            return 1
        }
        sudo -H env -u PYTHONPATH "$base_py" -m pip install \
            --upgrade --upgrade-strategy eager --break-system-packages "$wheel"
        bin_dir="$("$base_py" -c 'import sysconfig; print(sysconfig.get_path("scripts", scheme="posix_prefix"))')"
    fi

    local installed_version
    installed_version="$(env -u PYTHONPATH "$py" -c 'import importlib.metadata as m; print(m.version("expra-engine"))')"
    [[ "$installed_version" == "$expected_version" ]] || {
        echo "ERROR: installed $installed_version, expected $expected_version" >&2
        return 1
    }

    if [[ "$(uname -s)" == "Linux" ]] && ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0'; then
        echo "NOTE: the Qt editor needs the system library libxcb-cursor0 on X11 (not found)." >&2
        echo "      Debian/Ubuntu: sudo apt install libxcb-cursor0 | Fedora: sudo dnf install xcb-util-cursor | Arch: sudo pacman -S xcb-util-cursor" >&2
    fi

    if [[ "$mode" == "user" ]]; then
        local launcher_dir="${EXPRA_ENGINE_BIN_DIR:-$HOME/.local/bin}"
        mkdir -p "$launcher_dir"
        local launcher="$launcher_dir/expra-editor"
        if [[ -e "$launcher" || -L "$launcher" ]] && ! grep -q 'expra-engine' "$launcher" 2>/dev/null; then
            echo "WARNING: not overwriting unrelated executable $launcher" >&2
        else
            local tmp_launcher
            tmp_launcher="$(mktemp "${launcher}.XXXXXX")"
            printf '#!/usr/bin/env bash\nexec "%s/expra-editor" "$@"\n' "$bin_dir" >"$tmp_launcher"
            chmod +x "$tmp_launcher"
            mv -f "$tmp_launcher" "$launcher"
        fi
        echo "Installed Expra $installed_version. Launcher: $launcher"
    else
        echo "Installed Expra $installed_version. Launcher: $bin_dir/expra-editor"
        if [[ -x "$HOME/.local/bin/expra-editor" ]]; then
            echo "WARNING: per-user launcher $HOME/.local/bin/expra-editor shadows the system launcher" >&2
        fi
    fi
}
