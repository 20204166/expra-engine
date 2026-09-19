"""Release helpers for the packaged expra-engine wheel.

The build scripts use this module to:

1. compare the current source inputs with the newest built wheel,
2. auto-bump ``expra_engine._version.__version__`` using the four-segment
   decimal-style carry convention,
3. refresh ``dist/SHA256SUMS`` after a build, and
4. verify a built wheel before install (no forbidden content, expected
   members, entry points present).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

VersionBump = Literal["none", "patch", "feature", "minor"]

_VERSION_RE = re.compile(r'(__version__\s*=\s*")(?P<value>\d+\.\d+\.\d+\.\d+)(")')
_WHEEL_NAME_RE = re.compile(r"^expra_engine-(\d+\.\d+\.\d+\.\d+)-py3-none-any\.whl$")

_VERSION_MODULE = Path("src") / "expra_engine" / "_version.py"
_PACKAGE_ROOT = "expra_engine"
_TOP_LEVEL_MODULES: tuple[str, ...] = ()
_EXPECTED_ENTRY_POINT = "expra-editor = expra_engine.main:main"
_REQUIRED_PACKAGE_MEMBERS = (
    "expra_engine/__init__.py",
    "expra_engine/_version.py",
    "expra_engine/main.py",
    "expra_engine/core/__init__.py",
    "expra_engine/editor/__init__.py",
    "expra_engine/editor/app.py",
    "expra_engine/editor/delivery.py",
    "expra_engine/editor/instance_lock.py",
    "expra_engine/editor/persistence.py",
    "expra_engine/editor/preferences.py",
    "expra_engine/runtime/__init__.py",
    "expra_engine/runtime/clock.py",
    "expra_engine/runtime/event_queue.py",
    "expra_engine/runtime/events.py",
    "expra_engine/runtime/system.py",
)
_REQUIRED_PACKAGE_DATA = ("expra_engine/py.typed",)
_SYSTEM_ANALYZER_MARKERS = (
    "system_analyzer",
    "system-analyzer",
    "system analyzer",
    "maintenance/",
)


@dataclass(frozen=True)
class DiffSummary:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def _parse_version(raw: str) -> tuple[int, int, int, int]:
    pieces = raw.split(".")
    if len(pieces) != 4:
        raise ValueError(f"expected four version segments, got {raw!r}")
    return tuple(int(piece) for piece in pieces)  # type: ignore[return-value]


def _format_version(parts: tuple[int, int, int, int]) -> str:
    return ".".join(str(part) for part in parts)


def _bump_segment(
    parts: tuple[int, int, int, int], index: int
) -> tuple[int, int, int, int]:
    values = list(parts)
    values[index] += 1
    for position in range(index, 0, -1):
        if values[position] <= 9:
            break
        values[position] = 0
        values[position - 1] += 1
    return tuple(values)  # type: ignore[return-value]


def _compare_versions(left: str, right: str) -> int:
    l_parts = _parse_version(left)
    r_parts = _parse_version(right)
    if l_parts < r_parts:
        return -1
    if l_parts > r_parts:
        return 1
    return 0


def _pick_base_version(current: str, latest_wheel: str | None) -> str:
    if latest_wheel is None:
        return current
    return latest_wheel if _compare_versions(latest_wheel, current) > 0 else current


def _next_version(base: str, bump: VersionBump) -> str:
    parts = _parse_version(base)
    if bump == "none":
        return base
    if bump == "minor":
        return _format_version(_bump_segment((parts[0], parts[1], 0, 0), 1))
    if bump == "feature":
        return _format_version(_bump_segment((parts[0], parts[1], parts[2], 0), 2))
    return _format_version(_bump_segment(parts, 3))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _version_normalized(payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    text = _VERSION_RE.sub(r"\1__VERSION__\3", text)
    return text.encode("utf-8")


def _skip_source_path(path: Path) -> bool:
    parts = path.parts
    return "__pycache__" in parts or path.suffix == ".pyc"


def _collect_package_inputs(package_dir: Path) -> dict[str, str]:
    """Hash every package build input exactly as the wheel stores it.

    Keys match the wheel member names so ``_read_manifest_from_wheel`` can
    compare like-for-like. This includes package data, not only Python source.
    The ``_version.py`` value is version-normalized so an automatic bump never
    counts as a content change.
    """

    manifest: dict[str, str] = {}
    source_root = package_dir / "src" / _PACKAGE_ROOT
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or _skip_source_path(path):
            continue
        relative = path.relative_to(source_root).as_posix()
        payload = path.read_bytes()
        if relative == _VERSION_MODULE.name:
            payload = _version_normalized(payload)
        manifest[f"{_PACKAGE_ROOT}/{relative}"] = _sha256_bytes(payload)
    for name in _TOP_LEVEL_MODULES:
        path = package_dir / name
        manifest[name] = _sha256_bytes(path.read_bytes())
    return manifest


def _read_manifest_from_wheel(wheel_path: Path) -> dict[str, str]:
    """Derive build-input hashes from a wheel's stored members."""

    build_inputs: dict[str, str] = {}
    with zipfile.ZipFile(wheel_path) as archive:
        for name in archive.namelist():
            if name.endswith("/") or ".dist-info/" in name:
                continue
            payload = archive.read(name)
            if name == f"{_PACKAGE_ROOT}/{_VERSION_MODULE.name}":
                payload = _version_normalized(payload)
            build_inputs[name] = _sha256_bytes(payload)
    return build_inputs


def _newest_wheel(dist_dir: Path) -> Path | None:
    wheels: list[tuple[tuple[int, int, int, int], Path]] = []
    for path in dist_dir.glob("expra_engine-*.whl"):
        match = _WHEEL_NAME_RE.match(path.name)
        if match is None:
            continue
        wheels.append((_parse_version(match.group(1)), path))
    if not wheels:
        return None
    wheels.sort()
    return wheels[-1][1]


def _wheel_version(path: Path) -> str:
    match = _WHEEL_NAME_RE.match(path.name)
    if match is None:
        raise ValueError(f"unexpected wheel filename: {path.name}")
    return match.group(1)


def diff_manifests(
    previous: Mapping[str, str], current: Mapping[str, str]
) -> DiffSummary:
    before_keys = set(previous)
    after_keys = set(current)
    added = tuple(sorted(after_keys - before_keys))
    removed = tuple(sorted(before_keys - after_keys))
    changed = tuple(
        sorted(key for key in before_keys & after_keys if previous[key] != current[key])
    )
    return DiffSummary(added=added, removed=removed, changed=changed)


_MINOR_SURFACES = frozenset(
    {
        "expra_engine/main.py",
        "expra_engine/core/engine.py",
        "expra_engine/ui/editor_window.py",
    }
)

_FEATURE_SURFACES = frozenset(
    {
        "expra_engine/coordinators/coordinator.py",
        "expra_engine/editor/app.py",
        "expra_engine/editor/preferences.py",
        "expra_engine/runtime/event_queue.py",
        "expra_engine/core/scene.py",
    }
)


def classify_bump(diff: DiffSummary, *, override: str | None = None) -> VersionBump:
    """Choose the semantic bump level from the source diff.

    ``patch``: routine internal changes. ``feature``: user-visible behaviour
    or a new/changed non-core surface. ``minor``: structural additions or
    removals at the app's top level. ``none``: no build-input change.
    """

    if override:
        if override not in {"none", "patch", "feature", "minor", "auto"}:
            raise ValueError(f"unsupported bump override: {override}")
        if override != "auto":
            return override  # type: ignore[return-value]

    if not diff.has_changes:
        return "none"

    if diff.added or diff.removed:
        if any(area in _MINOR_SURFACES for area in (*diff.added, *diff.removed)):
            return "minor"
        return "feature"

    if any(key in _FEATURE_SURFACES for key in diff.changed):
        return "feature"
    return "patch"


def read_current_version(package_dir: Path) -> str:
    version_path = package_dir / _VERSION_MODULE
    match = _VERSION_RE.search(version_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"could not find __version__ in {version_path}")
    return match.group("value")


def write_current_version(package_dir: Path, version: str) -> None:
    version_path = package_dir / _VERSION_MODULE
    text = version_path.read_text(encoding="utf-8")
    updated, count = _VERSION_RE.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if count != 1:
        raise ValueError(f"could not update __version__ in {version_path}")
    version_path.write_text(updated, encoding="utf-8")


def rewrite_sha256sums(dist_dir: Path) -> None:
    wheel = _newest_wheel(dist_dir)
    lines = (
        [f"{_sha256_bytes(wheel.read_bytes())}  {wheel.name}"]
        if wheel is not None
        else []
    )
    (dist_dir / "SHA256SUMS").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )


def prepare_build(package_dir: Path, *, bump_override: str | None = None) -> str:
    """Auto-bump the version to the next build when source inputs changed."""

    current_manifest = _collect_package_inputs(package_dir)
    dist_dir = package_dir / "dist"
    latest_wheel = _newest_wheel(dist_dir)
    previous_manifest = (
        _read_manifest_from_wheel(latest_wheel) if latest_wheel is not None else {}
    )
    diff = diff_manifests(previous_manifest, current_manifest)
    current_version = read_current_version(package_dir)
    latest_version = _wheel_version(latest_wheel) if latest_wheel is not None else None
    base_version = _pick_base_version(current_version, latest_version)
    bump = classify_bump(diff, override=bump_override)
    next_version = _next_version(base_version, bump)
    if current_version != next_version:
        write_current_version(package_dir, next_version)
    print(f"current source version: {current_version}")
    print(f"latest built wheel: {latest_version or 'none'}")
    print(
        "diff against newest wheel: "
        f"{len(diff.changed)} changed, {len(diff.added)} added, {len(diff.removed)} removed"
    )
    print(f"selected bump: {bump}")
    print(f"next build version: {next_version}")
    return next_version


def sync_artifacts(package_dir: Path) -> Path:
    dist_dir = package_dir / "dist"
    wheel = _newest_wheel(dist_dir)
    if wheel is None:
        raise FileNotFoundError(f"no expra_engine wheel found in {dist_dir}")
    rewrite_sha256sums(dist_dir)
    print(f"SHA256SUMS refreshed for {wheel.name}")
    return wheel


def verify_wheel(wheel_path: Path) -> None:
    """Verify package boundaries, metadata, entry points, and wheel integrity."""

    forbidden = (".env", ".venv", "tests/", "node_modules", "__pycache__", ".pyc")
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        lower_names = {name.lower() for name in names}
        bad = [name for name in names if any(token in name.lower() for token in forbidden)]
        bad.extend(
            name
            for name in names
            if any(marker in name.lower() for marker in _SYSTEM_ANALYZER_MARKERS)
        )
        missing = [name for name in (*_REQUIRED_PACKAGE_MEMBERS, *_REQUIRED_PACKAGE_DATA)
                   if name not in names]
        if bad:
            raise ValueError(f"forbidden wheel content: {bad}")
        if missing:
            raise ValueError(f"missing wheel members: {missing}")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        entry_point_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(metadata_names) != 1:
            raise ValueError("wheel must contain exactly one dist-info/METADATA")
        if len(entry_point_names) != 1:
            raise ValueError("wheel must contain exactly one dist-info/entry_points.txt")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        entry_points = archive.read(entry_point_names[0]).decode("utf-8")
        version_payload = archive.read("expra_engine/_version.py").decode("utf-8")
    wheel_version = _wheel_version(wheel_path)
    metadata_match = re.search(r"^Version:\s*(\S+)\s*$", metadata, re.MULTILINE)
    source_match = _VERSION_RE.search(version_payload)
    if metadata_match is None or metadata_match.group(1) != wheel_version:
        raise ValueError("wheel filename, metadata, and package version do not match")
    if source_match is None or source_match.group("value") != wheel_version:
        raise ValueError("wheel package version does not match its filename")
    if _EXPECTED_ENTRY_POINT not in entry_points.splitlines():
        raise ValueError(f"missing expected CLI entry point: {_EXPECTED_ENTRY_POINT}")
    dev_parts = {"tests", "test", "docs", "dev", "examples"}
    if any(dev_parts.intersection(Path(name).parts) for name in lower_names):
        raise ValueError("wheel contains accidental tests or development material")
    print(f"sha256: {_sha256_bytes(wheel_path.read_bytes())}")
    print(f"contents OK: {len(names)} members; no forbidden paths")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Release helpers for expra-engine")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare-build", help="diff sources and auto-bump version")
    prepare.add_argument("--package-dir", required=True)
    prepare.add_argument(
        "--bump", default="auto", choices=["auto", "none", "patch", "feature", "minor"]
    )

    sync = sub.add_parser("sync-artifacts", help="refresh dist/SHA256SUMS")
    sync.add_argument("--package-dir", required=True)

    verify = sub.add_parser("verify-wheel", help="verify one built wheel")
    verify.add_argument("wheel", nargs="?", help="path to the wheel to verify")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "prepare-build":
        prepare_build(Path(args.package_dir).resolve(), bump_override=args.bump)
        return 0
    if args.command == "sync-artifacts":
        sync_artifacts(Path(args.package_dir).resolve())
        return 0
    if args.command == "verify-wheel":
        if not args.wheel:
            parser.error("verify-wheel requires a wheel path")
        verify_wheel(Path(args.wheel).resolve())
        return 0
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
