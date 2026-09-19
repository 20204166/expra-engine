"""Release pipeline for expra-engine.

Adapted from System Analyzer maintenance/_release.py — same proven logic
for manifest diffing, version bumping, SHA256SUMS, and wheel verification;
adapted to the expra-engine package layout.

Typical workflow::

    # Before building — bumps version if source changed
    python -c "
    import sys; sys.path.insert(0, 'src')
    from expra_engine._release import prepare_build
    from pathlib import Path
    prepare_build(Path('.'))
    "

    python -m build

    # After building — regenerate SHA256SUMS
    python -c "
    import sys; sys.path.insert(0, 'src')
    from expra_engine._release import sync_artifacts
    from pathlib import Path
    sync_artifacts(Path('.'))
    "
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PACKAGE_ROOT = "expra_engine"
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_WHEEL_NAME_RE = re.compile(r"^expra_engine-(\d+\.\d+\.\d+\.\d+)-py3-none-any\.whl$")
_SHA256SUMS_NAME = "SHA256SUMS"

# Surfaces that trigger a minor bump when first appearing in the wheel
_MINOR_SURFACES: frozenset[str] = frozenset(
    {
        "expra_engine/editor/",
        "expra_engine/core/",
    }
)

# Surfaces that trigger a feature bump
_FEATURE_SURFACES: frozenset[str] = frozenset(
    {
        "expra_engine/coordinators/",
        "expra_engine/ui/",
    }
)

BumpKind = Literal["none", "patch", "feature", "minor"]

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiffSummary:
    added: frozenset[str] = field(default_factory=frozenset)
    removed: frozenset[str] = field(default_factory=frozenset)
    changed: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


@dataclass(frozen=True, slots=True)
class BuildManifest:
    """Filename → content-hash mapping for either source or wheel."""

    entries: dict[str, str]


# ---------------------------------------------------------------------------
# Version I/O
# ---------------------------------------------------------------------------


def read_current_version(package_dir: Path) -> str:
    """Return the current ``__version__`` string from ``_version.py``."""
    version_path = package_dir / "src" / _PACKAGE_ROOT / "_version.py"
    text = version_path.read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if m is None:
        raise ValueError(f"Cannot find __version__ in {version_path}")
    return m.group(1)


def write_current_version(package_dir: Path, version: str) -> None:
    """Overwrite ``_version.py`` with the new *version* string."""
    version_path = package_dir / "src" / _PACKAGE_ROOT / "_version.py"
    version_path.write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def _bump_version(version: str, kind: BumpKind) -> str:
    parts = version.split(".")
    while len(parts) < 4:
        parts.append("0")
    major, minor, feature, patch = (int(p) for p in parts[:4])
    if kind == "minor":
        minor += 1
        feature = patch = 0
    elif kind == "feature":
        feature += 1
        patch = 0
    elif kind == "patch":
        patch += 1
    return f"{major}.{minor}.{feature}.{patch}"


# ---------------------------------------------------------------------------
# Manifest collection
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect_package_inputs(package_dir: Path) -> BuildManifest:
    """Hash every ``.py`` file under ``src/<package>/``."""
    source_root = package_dir / "src" / _PACKAGE_ROOT
    entries: dict[str, str] = {}
    for py_file in sorted(source_root.rglob("*.py")):
        rel = str(py_file.relative_to(package_dir / "src"))
        data = py_file.read_bytes()
        entries[rel] = _sha256_bytes(data)
    return BuildManifest(entries=entries)


def _version_normalized(payload: bytes) -> bytes:
    """Strip the version literal so a version bump alone doesn't appear as a diff."""
    return _VERSION_RE.sub('__version__ = "0.0.0.0"', payload.decode("utf-8")).encode("utf-8")


def _read_manifest_from_wheel(wheel_path: Path) -> BuildManifest:
    """Hash every ``.py`` member of the wheel (version-normalised)."""
    entries: dict[str, str] = {}
    with zipfile.ZipFile(wheel_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".py"):
                continue
            data = zf.read(name)
            if name.endswith("_version.py"):
                data = _version_normalized(data)
            entries[name] = _sha256_bytes(data)
    return BuildManifest(entries=entries)


def _newest_wheel(dist_dir: Path) -> Path | None:
    """Return the newest wheel in *dist_dir* by parsed version, or ``None``."""
    candidates: list[tuple[tuple[int, ...], Path]] = []
    if not dist_dir.is_dir():
        return None
    for p in dist_dir.iterdir():
        m = _WHEEL_NAME_RE.match(p.name)
        if m:
            ver_tuple = tuple(int(x) for x in m.group(1).split("."))
            candidates.append((ver_tuple, p))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[-1][1]


# ---------------------------------------------------------------------------
# Manifest diffing and bump classification
# ---------------------------------------------------------------------------


def diff_manifests(previous: BuildManifest, current: BuildManifest) -> DiffSummary:
    """Return the symmetric diff between two manifests."""
    prev_keys = set(previous.entries)
    curr_keys = set(current.entries)
    return DiffSummary(
        added=frozenset(curr_keys - prev_keys),
        removed=frozenset(prev_keys - curr_keys),
        changed=frozenset(
            k for k in prev_keys & curr_keys if previous.entries[k] != current.entries[k]
        ),
    )


def classify_bump(diff: DiffSummary, override: BumpKind | None = None) -> BumpKind:
    """Choose the appropriate bump kind for *diff*."""
    if override is not None:
        return override
    if not diff.has_changes:
        return "none"
    all_changed = diff.added | diff.removed | diff.changed
    if any(path.startswith(surface) for path in all_changed for surface in _MINOR_SURFACES):
        return "minor"
    if any(path.startswith(surface) for path in all_changed for surface in _FEATURE_SURFACES):
        return "feature"
    return "patch"


# ---------------------------------------------------------------------------
# Public pipeline
# ---------------------------------------------------------------------------


def prepare_build(package_dir: Path, bump_override: BumpKind | None = None) -> str:
    """Compare source vs. newest wheel, bump version if needed, return new version.

    Writes ``_version.py`` only when a bump is required.  Returns the
    resulting version string (unchanged if ``"none"``).
    """
    current_version = read_current_version(package_dir)
    dist_dir = package_dir / "dist"
    newest = _newest_wheel(dist_dir)

    if newest is None:
        # First build — always bump to patch at minimum
        kind: BumpKind = bump_override if bump_override is not None else "patch"
    else:
        source_manifest = _collect_package_inputs(package_dir)
        # Normalise source for comparison (strip version marker)
        norm_source: dict[str, str] = {}
        for rel_path, _digest in source_manifest.entries.items():
            src_file = package_dir / "src" / rel_path
            raw = src_file.read_bytes()
            if rel_path.endswith("_version.py"):
                raw = _version_normalized(raw)
            norm_source[rel_path] = _sha256_bytes(raw)
        wheel_manifest = _read_manifest_from_wheel(newest)
        # Remap wheel keys (e.g. expra_engine/foo.py) to source keys
        remapped_wheel: dict[str, str] = dict(wheel_manifest.entries.items())
        source_bm = BuildManifest(entries=norm_source)
        wheel_bm = BuildManifest(entries=remapped_wheel)
        diff = diff_manifests(wheel_bm, source_bm)
        kind = classify_bump(diff, bump_override)

    if kind == "none":
        return current_version

    new_version = _bump_version(current_version, kind)
    write_current_version(package_dir, new_version)
    print(f"Version bumped: {current_version} → {new_version} ({kind})")
    return new_version


def sync_artifacts(package_dir: Path) -> None:
    """Rewrite ``dist/SHA256SUMS`` with hashes of all wheels in ``dist/``."""
    dist_dir = package_dir / "dist"
    if not dist_dir.is_dir():
        print("No dist/ directory; nothing to hash.")
        return

    lines: list[str] = []
    for wheel in sorted(dist_dir.glob("*.whl")):
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        lines.append(f"{digest}  {wheel.name}")

    if not lines:
        print("No wheels found in dist/.")
        return

    sums_path = dist_dir / _SHA256SUMS_NAME
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {sums_path} ({len(lines)} entries)")


def verify_wheel(wheel_path: Path) -> list[str]:
    """Return a list of problems found in *wheel_path* (empty = OK)."""
    problems: list[str] = []
    try:
        with zipfile.ZipFile(wheel_path) as zf:
            names = set(zf.namelist())
    except (zipfile.BadZipFile, OSError) as exc:
        return [f"Cannot open wheel: {exc}"]

    # Must contain __init__.py
    if f"{_PACKAGE_ROOT}/__init__.py" not in names:
        problems.append(f"Missing {_PACKAGE_ROOT}/__init__.py")

    # Must not contain secrets or credentials
    forbidden_patterns = [".env", "id_rsa", "id_ed25519", "credentials.json"]
    for name in names:
        for pat in forbidden_patterns:
            if pat in name:
                problems.append(f"Suspicious file in wheel: {name}")

    # dist-info must exist
    dist_info = [n for n in names if n.endswith(".dist-info/METADATA")]
    if not dist_info:
        problems.append("Missing .dist-info/METADATA")

    return problems
