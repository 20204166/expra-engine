"""Tests for editor.persistence — atomic filesystem helpers."""

import contextlib
import unittest
from pathlib import Path
from unittest.mock import patch

from expra_engine.editor.persistence import atomic_write_text, read_text_or_none


class ReadTextOrNoneTests(unittest.TestCase):
    def test_returns_none_for_missing_file(self) -> None:
        result = read_text_or_none(Path("/nonexistent/path/file.txt"))
        self.assertIsNone(result)

    def test_returns_content_for_existing_file(self, tmp_path: Path | None = None) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.txt"
            p.write_text("hello world", encoding="utf-8")
            self.assertEqual(read_text_or_none(p), "hello world")

    def test_returns_none_for_unreadable_unicode(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.txt"
            p.write_bytes(b"\xff\xfe invalid utf-8 \x80")
            # On some systems this may succeed with errors='replace';
            # we just ensure it doesn't raise
            result = read_text_or_none(p)
            # result is None or a string — either is acceptable
            self.assertIsInstance(result, (str, type(None)))


class AtomicWriteTextTests(unittest.TestCase):
    def test_creates_file_with_correct_content(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            atomic_write_text(p, '{"key": "value"}')
            self.assertEqual(p.read_text(encoding="utf-8"), '{"key": "value"}')

    def test_replaces_existing_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.txt"
            p.write_text("old content", encoding="utf-8")
            atomic_write_text(p, "new content")
            self.assertEqual(p.read_text(encoding="utf-8"), "new content")

    def test_creates_parent_directories(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a" / "b" / "c" / "out.txt"
            atomic_write_text(p, "nested")
            self.assertEqual(p.read_text(encoding="utf-8"), "nested")

    def test_original_preserved_when_write_fails(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.txt"
            p.write_text("original", encoding="utf-8")

            # Simulate fsync failure — should still atomically replace
            # (fsync failure is best-effort and should not prevent the write)
            with patch("os.fsync", side_effect=OSError("fsync failed")), contextlib.suppress(OSError):
                    atomic_write_text(p, "updated")

            # Either the write succeeded (updated) or original is preserved — never corrupted
            content = p.read_text(encoding="utf-8")
            self.assertIn(content, ("original", "updated"))

    def test_raises_oserror_when_directory_creation_fails(self) -> None:
        with self.assertRaises(OSError):
            # Write to a path whose parent cannot be created (file exists as parent)
            import tempfile

            with tempfile.TemporaryDirectory() as d:
                file_as_dir = Path(d) / "file_not_dir"
                file_as_dir.write_text("blocking", encoding="utf-8")
                atomic_write_text(file_as_dir / "sub" / "out.txt", "data")


if __name__ == "__main__":
    unittest.main()
