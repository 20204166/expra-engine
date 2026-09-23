"""Path resolution helpers: env/user expansion, config discovery locations,
venv interpreter resolution, and root-containment checks.

All path handling goes through pathlib -- no '/'-string concatenation -- so
this stays correct on Linux, macOS, Windows, and WSL.
"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env_vars(text: str) -> str:
    """Substitute ``${VAR}`` references with the current environment's values.

    An unset variable is left as-is (rather than becoming an empty string) so
    a config typo is visible instead of silently resolving to a bare path.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    return _ENV_VAR_RE.sub(_sub, text)


def resolve_path(raw: str, *, base_dir: Path) -> Path:
    """Resolve a config-supplied path: ``${ENV}`` substitution, ``~``
    expansion, then relative resolution against ``base_dir`` (the config
    file's own directory, per the spec's "relative paths relative to the
    config file" rule).
    """

    expanded = expand_env_vars(raw)
    expanded = os.path.expanduser(expanded)
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def user_config_dir(app_name: str = "expra-mcp") -> Path:
    """OS-appropriate user configuration directory."""

    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / app_name
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / app_name


def venv_python(root: Path) -> Path | None:
    """Return the conventional venv interpreter path under ``root`` if it
    actually exists; ``None`` otherwise (never silently pick a system
    interpreter just because *a* Python was found).
    """

    if platform.system() == "Windows":
        candidate = root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def is_contained(path: Path, root: Path) -> bool:
    """True if ``path`` resolves to ``root`` or somewhere nested under it,
    after resolving symlinks on both sides. Used to enforce the read-only
    reference-source containment boundary and to detect whether
    ``expra_engine`` imported from the configured source tree.
    """

    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
    except OSError:
        return False
    return resolved_path == resolved_root or resolved_root in resolved_path.parents
