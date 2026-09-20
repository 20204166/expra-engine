"""Tests for BytecodeCompiler."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from expra_engine.export.bytecode import BytecodeCompiler


class TestBytecodeCompiler(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._src = self._tmp / "src"
        self._dst = self._tmp / "dst"
        self._src.mkdir()
        self._dst.mkdir()

    def _compile(
        self, cancel: threading.Event | None = None
    ) -> int:
        cancel = cancel or threading.Event()
        return BytecodeCompiler().compile(
            self._src,
            self._dst,
            cancel=cancel,
            progress=lambda _: None,
        )

    def test_compiles_single_file(self) -> None:
        (self._src / "hello.py").write_text("x = 1")
        count = self._compile()
        self.assertEqual(count, 1)
        self.assertTrue((self._dst / "hello.pyc").exists())

    def test_compiles_nested(self) -> None:
        (self._src / "sub").mkdir()
        (self._src / "sub" / "mod.py").write_text("y = 2")
        count = self._compile()
        self.assertEqual(count, 1)
        self.assertTrue((self._dst / "sub" / "mod.pyc").exists())

    def test_skips_pycache(self) -> None:
        (self._src / "__pycache__").mkdir()
        (self._src / "__pycache__" / "cached.py").write_text("z = 3")
        count = self._compile()
        self.assertEqual(count, 0)

    def test_cancellation_stops_early(self) -> None:
        for i in range(10):
            (self._src / f"f{i}.py").write_text(f"x = {i}")
        cancel = threading.Event()
        cancel.set()
        count = self._compile(cancel=cancel)
        self.assertEqual(count, 0)

    def test_syntax_error_raises(self) -> None:
        (self._src / "bad.py").write_text("def (")
        with self.assertRaises(RuntimeError):
            self._compile()

    def test_progress_called(self) -> None:
        (self._src / "a.py").write_text("pass")
        messages: list[str] = []
        cancel = threading.Event()
        BytecodeCompiler().compile(
            self._src,
            self._dst,
            cancel=cancel,
            progress=messages.append,
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("a.py", messages[0])

    def test_no_files_returns_zero(self) -> None:
        count = self._compile()
        self.assertEqual(count, 0)
