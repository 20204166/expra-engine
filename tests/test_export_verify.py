"""Tests for verify_export()."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from expra_engine.export.verify import ExportVerificationError, verify_export


def _write_valid_manifests(build_dir: Path) -> None:
    build_manifest = {
        "game_name": "Test",
        "game_version": "1.0.0",
        "engine_version": "0.1.7.1",
        "target": "windows",
        "python_version": "3.12.4",
        "arch": "amd64",
        "compile_bytecode": True,
        "entry_point": "__main__.py",
        "build_timestamp": "2026-09-20T00:00:00+00:00",
    }
    (build_dir / "build_manifest.json").write_text(json.dumps(build_manifest))
    (build_dir / "asset_manifest.json").write_text(json.dumps({"entries": []}))


class TestVerifyExport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._build = self._tmp / "build"
        self._build.mkdir()

    def test_valid_build_passes(self) -> None:
        _write_valid_manifests(self._build)
        verify_export(self._build)  # must not raise

    def test_missing_directory_fails(self) -> None:
        with self.assertRaises(ExportVerificationError):
            verify_export(self._tmp / "no_such_dir")

    def test_missing_build_manifest_fails(self) -> None:
        (self._build / "asset_manifest.json").write_text(json.dumps({"entries": []}))
        with self.assertRaises(ExportVerificationError):
            verify_export(self._build)

    def test_missing_asset_manifest_fails(self) -> None:
        build_manifest = {
            "game_name": "T",
            "game_version": "1.0.0",
            "engine_version": "0",
            "target": "windows",
            "python_version": "3.12.4",
            "arch": "amd64",
            "compile_bytecode": True,
            "entry_point": "__main__.py",
            "build_timestamp": "2026-01-01T00:00:00+00:00",
        }
        (self._build / "build_manifest.json").write_text(json.dumps(build_manifest))
        with self.assertRaises(ExportVerificationError):
            verify_export(self._build)

    def test_corrupted_build_manifest_fails(self) -> None:
        (self._build / "build_manifest.json").write_text("{bad json")
        (self._build / "asset_manifest.json").write_text(json.dumps({"entries": []}))
        with self.assertRaises(ExportVerificationError):
            verify_export(self._build)

    def test_missing_required_key_fails(self) -> None:
        incomplete = {
            "game_name": "T",
            "game_version": "1.0.0",
            # intentionally missing the other required keys
        }
        (self._build / "build_manifest.json").write_text(json.dumps(incomplete))
        (self._build / "asset_manifest.json").write_text(json.dumps({"entries": []}))
        with self.assertRaises(ExportVerificationError):
            verify_export(self._build)

    def test_asset_manifest_missing_entries_key_fails(self) -> None:
        _write_valid_manifests(self._build)
        (self._build / "asset_manifest.json").write_text(json.dumps({"not_entries": []}))
        with self.assertRaises(ExportVerificationError):
            verify_export(self._build)

    def test_fails_closed_not_open(self) -> None:
        # verify_export must never silently succeed on a broken build
        (self._build / "build_manifest.json").write_text("{}")
        (self._build / "asset_manifest.json").write_text(json.dumps({"entries": []}))
        with self.assertRaises(ExportVerificationError):
            verify_export(self._build)

    def test_export_containing_editor_import_is_rejected(self) -> None:
        _write_valid_manifests(self._build)
        (self._build / "main.py").write_text("import expra_engine.editor\nprint('hello')\n")

        with self.assertRaisesRegex(ExportVerificationError, "forbidden"):
            verify_export(self._build)

    def test_export_containing_tkinter_import_is_rejected(self) -> None:
        _write_valid_manifests(self._build)
        (self._build / "main.py").write_text("import tkinter\n")

        with self.assertRaisesRegex(ExportVerificationError, "forbidden"):
            verify_export(self._build)

    def test_clean_export_passes_with_python_file(self) -> None:
        _write_valid_manifests(self._build)
        (self._build / "main.py").write_text("print('hello world')\n")

        verify_export(self._build)
