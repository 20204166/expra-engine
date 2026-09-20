"""Tests for WindowsPackager and LinuxPackager (no internet required).

All network calls are replaced by injected fake downloaders or stubs.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from expra_engine.export.packager import (
    LinuxPackager,
    WindowsPackager,
    _is_blocked,
)


def _make_fake_python_zip(dest_zip: Path, python_version: str = "3.12.4") -> None:
    """Create a minimal fake Windows embedded Python zip for tests."""
    major, minor, _ = python_version.split(".")
    with zipfile.ZipFile(dest_zip, "w") as zf:
        zf.writestr(f"python{major}{minor}._pth", "python312.zip\n.\n")
        zf.writestr("python.exe", "stub")
        zf.writestr("pythonw.exe", "stub")


def _fake_downloader(url: str, dest: Path) -> None:
    """Fake downloader that writes a valid Python zip without network."""
    # Extract version from URL: python-3.12.4-embed-amd64.zip
    name = dest.name  # e.g. python-3.12.4-embed-amd64.zip
    version = name.split("-")[1]  # "3.12.4"
    _make_fake_python_zip(dest, version)


class TestIsBlocked(unittest.TestCase):
    def test_tkinter_blocked(self) -> None:
        self.assertTrue(_is_blocked("tkinter"))

    def test_ttkbootstrap_blocked(self) -> None:
        self.assertTrue(_is_blocked("ttkbootstrap==1.2.0"))

    def test_numpy_not_blocked(self) -> None:
        self.assertFalse(_is_blocked("numpy"))

    def test_pillow_not_blocked(self) -> None:
        self.assertFalse(_is_blocked("Pillow==10.0.0"))


class TestWindowsPackagerRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())

    def test_extracts_python_with_fake_downloader(self) -> None:
        dest = self._tmp / "python"
        cache = self._tmp / "cache"
        cancel = threading.Event()
        msgs: list[str] = []

        WindowsPackager().install_runtime(
            "3.12.4",
            "amd64",
            dest,
            cache_dir=cache,
            cancel=cancel,
            progress=msgs.append,
            downloader=_fake_downloader,
        )

        self.assertTrue(dest.is_dir())
        self.assertTrue((dest / "python.exe").exists())

    def test_uses_cached_zip(self) -> None:
        dest = self._tmp / "python"
        cache = self._tmp / "cache"
        cache.mkdir()
        cached_zip = cache / "python-3.12.4-embed-amd64.zip"
        _make_fake_python_zip(cached_zip)

        download_called = []

        def fail_if_called(url: str, path: Path) -> None:
            download_called.append(url)

        cancel = threading.Event()
        WindowsPackager().install_runtime(
            "3.12.4",
            "amd64",
            dest,
            cache_dir=cache,
            cancel=cancel,
            progress=lambda _: None,
            downloader=fail_if_called,
        )

        self.assertEqual(download_called, [], "should not have called downloader with cached zip")
        self.assertTrue(dest.is_dir())

    def test_cancellation_before_download(self) -> None:
        dest = self._tmp / "python"
        cache = self._tmp / "cache"
        cancel = threading.Event()
        cancel.set()

        download_called = []
        WindowsPackager().install_runtime(
            "3.12.4",
            "amd64",
            dest,
            cache_dir=cache,
            cancel=cancel,
            progress=lambda _: None,
            downloader=lambda u, p: download_called.append(u),
        )
        self.assertEqual(download_called, [])

    def test_pth_patched(self) -> None:
        dest = self._tmp / "python"
        cache = self._tmp / "cache"
        cancel = threading.Event()
        WindowsPackager().install_runtime(
            "3.12.4",
            "amd64",
            dest,
            cache_dir=cache,
            cancel=cancel,
            progress=lambda _: None,
            downloader=_fake_downloader,
        )
        pth = dest / "python312._pth"
        self.assertTrue(pth.exists())
        content = pth.read_text()
        self.assertIn("import site", content)

    def test_pth_not_double_patched(self) -> None:
        dest = self._tmp / "python"
        cache = self._tmp / "cache"
        cancel = threading.Event()
        for _ in range(2):
            WindowsPackager().install_runtime(
                "3.12.4",
                "amd64",
                dest,
                cache_dir=cache,
                cancel=cancel,
                progress=lambda _: None,
                downloader=_fake_downloader,
            )
        pth = dest / "python312._pth"
        content = pth.read_text()
        self.assertEqual(content.count("import site"), 1)


class TestWindowsPackagerLauncher(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())

    def test_makes_bat_file(self) -> None:
        WindowsPackager().make_launcher(
            self._tmp,
            "My Game",
            "__main__.py",
            "My_Game",
            is_pyc=False,
            debug=False,
        )
        bat = self._tmp / "My_Game.bat"
        self.assertTrue(bat.exists())
        content = bat.read_text()
        self.assertIn("pythonw.exe", content)
        self.assertIn("__main__.py", content)

    def test_makes_debug_bat_file(self) -> None:
        WindowsPackager().make_launcher(
            self._tmp,
            "My Game",
            "__main__.py",
            "My_Game",
            is_pyc=False,
            debug=True,
        )
        bat = self._tmp / "My_Game_debug.bat"
        self.assertTrue(bat.exists())
        content = bat.read_text()
        self.assertIn("python.exe", content)
        self.assertIn("log.txt", content)

    def test_bat_uses_pyc_suffix(self) -> None:
        WindowsPackager().make_launcher(
            self._tmp,
            "Game",
            "__main__.py",
            "Game",
            is_pyc=True,
            debug=False,
        )
        content = (self._tmp / "Game.bat").read_text()
        self.assertIn("__main__.pyc", content)


class TestLinuxPackagerLauncher(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())

    def test_makes_sh_file(self) -> None:
        LinuxPackager().make_launcher(
            self._tmp,
            "My Game",
            "__main__.py",
            "My_Game",
            is_pyc=False,
            debug=False,
        )
        sh = self._tmp / "My_Game.sh"
        self.assertTrue(sh.exists())
        self.assertTrue(sh.stat().st_mode & 0o111)  # executable
        content = sh.read_text()
        self.assertIn("__main__.py", content)

    def test_makes_debug_sh_file(self) -> None:
        LinuxPackager().make_launcher(
            self._tmp,
            "My Game",
            "__main__.py",
            "My_Game",
            is_pyc=False,
            debug=True,
        )
        sh = self._tmp / "My_Game_debug.sh"
        self.assertTrue(sh.exists())
        content = sh.read_text()
        self.assertIn("log.txt", content)

    def test_space_in_name_replaced(self) -> None:
        LinuxPackager().make_launcher(
            self._tmp,
            "Space Game",
            "__main__.py",
            "Space_Game",
            is_pyc=False,
            debug=False,
        )
        self.assertTrue((self._tmp / "Space_Game.sh").exists())
