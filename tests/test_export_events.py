"""Tests for ExportProgressEvent and ExportPhase."""

from __future__ import annotations

import unittest

from expra_engine.export.events import ExportPhase, ExportProgressEvent


class TestExportPhase(unittest.TestCase):
    def test_all_phases_are_strings(self) -> None:
        for phase in ExportPhase:
            self.assertIsInstance(phase.value, str)

    def test_phase_names(self) -> None:
        names = {p.value for p in ExportPhase}
        self.assertIn("planning", names)
        self.assertIn("done", names)
        self.assertIn("cancelled", names)
        self.assertIn("failed", names)


class TestExportProgressEvent(unittest.TestCase):
    def test_creation(self) -> None:
        e = ExportProgressEvent(phase=ExportPhase.PLANNING, message="hello", percent=0)
        self.assertEqual(e.percent, 0)
        self.assertEqual(e.message, "hello")

    def test_frozen(self) -> None:
        e = ExportProgressEvent(phase=ExportPhase.DONE, message="done", percent=100)
        with self.assertRaises((AttributeError, TypeError)):
            e.percent = 50  # type: ignore[misc]

    def test_percent_boundary(self) -> None:
        e = ExportProgressEvent(phase=ExportPhase.VERIFYING, message="v", percent=100)
        self.assertEqual(e.percent, 100)
