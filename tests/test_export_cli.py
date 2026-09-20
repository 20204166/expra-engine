"""Tests for the export CLI parser and main function."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from expra_engine.export.cli import build_parser, cli_main


class TestBuildParser(unittest.TestCase):
    def test_required_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            project.mkdir()
            args = build_parser().parse_args([str(project), "--target", "windows"])
            self.assertEqual(args.target, "windows")
            self.assertEqual(args.project, project)

    def test_default_game_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            project.mkdir()
            args = build_parser().parse_args([str(project), "--target", "linux"])
            self.assertEqual(args.game_version, "1.0.0")

    def test_no_bytecode_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            project.mkdir()
            args = build_parser().parse_args([str(project), "--target", "windows", "--no-bytecode"])
            self.assertTrue(args.no_bytecode)

    def test_arch_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            project.mkdir()
            args = build_parser().parse_args([str(project), "--target", "windows"])
            self.assertEqual(args.arch, "amd64")


class TestCliMain(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._project = self._tmp / "mygame"
        self._project.mkdir()
        (self._project / "__main__.py").write_text("pass")
        self._output = self._tmp / "builds"
        self._output.mkdir()

    def test_returns_1_for_missing_entry_point(self) -> None:
        rc = cli_main(
            [
                str(self._project),
                "--target",
                "windows",
                "--entry-point",
                "missing.py",
                "--output",
                str(self._output),
            ]
        )
        self.assertEqual(rc, 1)

    def test_returns_1_for_bad_game_name(self) -> None:
        rc = cli_main(
            [
                str(self._project),
                "--target",
                "windows",
                "--game-name",
                "@bad/name",
                "--output",
                str(self._output),
            ]
        )
        self.assertEqual(rc, 1)

    def test_export_called_with_mock(self) -> None:
        # Patch GameExporter.export to avoid real network/build
        from expra_engine.export import exporter as exporter_module

        fake_result = self._output / "mygame_windows"
        fake_result.mkdir(exist_ok=True)

        with patch.object(exporter_module.GameExporter, "export", return_value=fake_result):
            rc = cli_main(
                [
                    str(self._project),
                    "--target",
                    "windows",
                    "--output",
                    str(self._output),
                ]
            )
        self.assertEqual(rc, 0)

    def test_export_error_returns_1(self) -> None:
        from expra_engine.export import exporter as exporter_module

        with patch.object(
            exporter_module.GameExporter,
            "export",
            side_effect=exporter_module.ExportError("boom"),
        ):
            rc = cli_main(
                [
                    str(self._project),
                    "--target",
                    "windows",
                    "--output",
                    str(self._output),
                ]
            )
        self.assertEqual(rc, 1)
