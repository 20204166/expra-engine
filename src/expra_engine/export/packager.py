"""Target-aware runtime packager.

WindowsPackager: downloads Windows embeddable Python, extracts it, patches
the ._pth file, then pip-downloads platform wheels for the target.

LinuxPackager: creates a venv, installs packages into it.

Both accept a `downloader` kwarg for unit-testing without network access.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path


class PackagerError(RuntimeError):
    pass


# Packages that must never be installed into exported games.
_BLOCKED_PACKAGES: frozenset[str] = frozenset({
    "tkinter", "ttkbootstrap", "expra-engine-editor",
})


def _is_blocked(pkg: str) -> bool:
    name = pkg.split("==")[0].split("@")[0].strip().lower().replace("-", "_")
    return any(name.startswith(b.replace("-", "_")) for b in _BLOCKED_PACKAGES)


class TargetPackager(ABC):
    """Copy/install the runtime and packages for the target platform."""

    @abstractmethod
    def install_runtime(
        self,
        python_version: str,
        arch: str,
        dest: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: Callable[[str], None],
        downloader: Callable[[str, Path], None] | None = None,
    ) -> None: ...

    @abstractmethod
    def install_packages(
        self,
        packages: list[str],
        python_version: str,
        arch: str,
        site_packages: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: Callable[[str], None],
    ) -> None: ...

    @abstractmethod
    def make_launcher(
        self,
        build_dir: Path,
        game_name: str,
        entry_point: str,
        source_subdir: str,
        *,
        is_pyc: bool,
        debug: bool,
    ) -> None: ...


class WindowsPackager(TargetPackager):
    """Windows embedded Python packager (architecture-aware, cached)."""

    def install_runtime(
        self,
        python_version: str,
        arch: str,
        dest: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: Callable[[str], None],
        downloader: Callable[[str, Path], None] | None = None,
    ) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        zip_name = f"python-{python_version}-embed-{arch}.zip"
        cached_zip = cache_dir / zip_name

        if not cached_zip.exists():
            if cancel.is_set():
                return
            url = f"https://www.python.org/ftp/python/{python_version}/{zip_name}"
            progress(f"Downloading Windows embedded Python {python_version} ({arch})")
            if downloader is None:
                import urllib.request
                urllib.request.urlretrieve(url, cached_zip)
            else:
                downloader(url, cached_zip)
        else:
            progress(f"Using cached embedded Python {python_version} ({arch})")

        if cancel.is_set():
            return

        progress("Extracting Python runtime")
        with zipfile.ZipFile(cached_zip) as zf:
            zf.extractall(dest)

        major, minor, _ = python_version.split(".")
        pth_file = dest / f"python{major}{minor}._pth"
        if pth_file.exists():
            existing = pth_file.read_text()
            if "import site" not in existing:
                with pth_file.open("a") as f:
                    f.write("\n..\nimport site\n")

    def install_packages(
        self,
        packages: list[str],
        python_version: str,
        arch: str,
        site_packages: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: Callable[[str], None],
    ) -> None:
        site_packages.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        major, minor, _ = python_version.split(".")
        abi = f"cp{major}{minor}"
        python_tag = f"{major}.{minor}"
        platform_map = {"amd64": "win_amd64", "arm64": "win_arm64"}
        platform_tag = platform_map.get(arch.lower(), f"win_{arch.lower()}")

        for pkg in packages:
            if cancel.is_set():
                return
            if _is_blocked(pkg):
                progress(f"Skipping blocked package: {pkg}")
                continue
            progress(f"Downloading {pkg}")
            result = subprocess.run(
                [
                    sys.executable, "-m", "pip", "download",
                    "--platform", platform_tag,
                    "--python-version", python_tag,
                    "--implementation", "cp",
                    "--abi", abi,
                    "--only-binary=:all:",
                    "--no-deps",
                    "--no-cache-dir",
                    "--dest", str(cache_dir),
                    pkg,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise PackagerError(
                    f"Failed to download {pkg} for {platform_tag}: {result.stderr.strip()}"
                )

        if cancel.is_set():
            return

        progress("Extracting wheels into site-packages")
        for wheel in sorted(cache_dir.glob("*.whl")):
            with zipfile.ZipFile(wheel, "r") as z:
                z.extractall(site_packages)

    def make_launcher(
        self,
        build_dir: Path,
        game_name: str,
        entry_point: str,
        source_subdir: str,
        *,
        is_pyc: bool,
        debug: bool,
    ) -> None:
        suffix = "c" if is_pyc else ""
        safe_name = game_name.replace(" ", "_")
        launch_name = f"{safe_name}_debug.bat" if debug else f"{safe_name}.bat"
        python_exe = "python.exe" if debug else "pythonw.exe"
        launcher = build_dir / launch_name
        with launcher.open("w", newline="\r\n") as f:
            f.write("@echo off\r\n")
            f.write("chcp 65001 >nul\r\n")
            f.write("set PYTHONIOENCODING=utf-8\r\n")
            f.write("\r\n")
            f.write(f'pushd "{source_subdir}"\r\n')
            if debug:
                f.write(
                    f'call "..\\python\\{python_exe}" "{entry_point}{suffix}"'
                    f' > "..\\log.txt" 2>&1\r\n'
                )
            else:
                f.write(f'call "..\\python\\{python_exe}" "{entry_point}{suffix}"\r\n')
            f.write("popd\r\n")


class LinuxPackager(TargetPackager):
    """Linux packager — venv-based runtime bundle."""

    def install_runtime(
        self,
        python_version: str,
        arch: str,
        dest: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: Callable[[str], None],
        downloader: Callable[[str, Path], None] | None = None,
    ) -> None:
        if cancel.is_set():
            return
        progress(f"Creating Linux runtime venv (Python {python_version})")
        dest.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(dest)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise PackagerError(f"Failed to create venv: {result.stderr.strip()}")

    def install_packages(
        self,
        packages: list[str],
        python_version: str,
        arch: str,
        site_packages: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: Callable[[str], None],
    ) -> None:
        # Walk up to find bin/pip
        venv_pip: Path | None = None
        for parent in site_packages.parents:
            candidate = parent / "bin" / "pip"
            if candidate.exists():
                venv_pip = candidate
                break
        if venv_pip is None:
            raise PackagerError("Could not find pip in venv")

        filtered = [p for p in packages if not _is_blocked(p)]
        if not filtered:
            return
        if cancel.is_set():
            return
        progress(f"Installing {len(filtered)} packages into venv")
        result = subprocess.run(
            [str(venv_pip), "install", "--no-cache-dir", *filtered],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise PackagerError(f"pip install failed: {result.stderr.strip()}")

    def make_launcher(
        self,
        build_dir: Path,
        game_name: str,
        entry_point: str,
        source_subdir: str,
        *,
        is_pyc: bool,
        debug: bool,
    ) -> None:
        suffix = "c" if is_pyc else ""
        safe_name = game_name.replace(" ", "_")
        launch_name = f"{safe_name}_debug.sh" if debug else f"{safe_name}.sh"
        launcher = build_dir / launch_name
        python_rel = "./runtime/bin/python3"
        with launcher.open("w", newline="\n") as f:
            f.write("#!/bin/sh\n")
            f.write("set -e\n")
            f.write('SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n')
            f.write(f'cd "$SCRIPT_DIR/{source_subdir}"\n')
            if debug:
                f.write(
                    f'"$SCRIPT_DIR/{python_rel}" "{entry_point}{suffix}" "$@"'
                    f' 2>&1 | tee "$SCRIPT_DIR/log.txt"\n'
                )
            else:
                f.write(f'"$SCRIPT_DIR/{python_rel}" "{entry_point}{suffix}" "$@"\n')
        launcher.chmod(0o755)
