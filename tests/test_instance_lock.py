"""Tests for editor.instance_lock — cross-platform single-instance lock."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from expra_engine.editor.instance_lock import InstanceLock, acquire


class InstanceLockTests(unittest.TestCase):
    def test_acquire_succeeds_first_time(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            lock_path = Path(d) / "expra.lock"
            lock = acquire(lock_path)
            try:
                self.assertIsNotNone(lock)
            finally:
                if lock is not None:
                    lock.release()

    def test_acquire_fails_when_already_held(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            lock_path = Path(d) / "expra.lock"
            lock = acquire(lock_path)
            self.assertIsNotNone(lock)
            try:
                # Try to acquire from a subprocess — should fail
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        f"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from expra_engine.editor.instance_lock import acquire
lock = acquire(Path(r'{lock_path}'))
sys.exit(0 if lock is None else 1)
""",
                    ],
                    cwd=str(Path(__file__).parent.parent),
                    capture_output=True,
                    timeout=10,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"Expected acquire to fail in subprocess but got rc={result.returncode}: {result.stderr.decode()}",
                )
            finally:
                if lock is not None:
                    lock.release()

    def test_release_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            lock_path = Path(d) / "expra.lock"
            lock = acquire(lock_path)
            self.assertIsNotNone(lock)
            assert lock is not None
            lock.release()
            lock.release()  # must not raise

    def test_release_allows_reacquire(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            lock_path = Path(d) / "expra.lock"
            lock1 = acquire(lock_path)
            self.assertIsNotNone(lock1)
            assert lock1 is not None
            lock1.release()

            lock2 = acquire(lock_path)
            try:
                self.assertIsNotNone(lock2)
            finally:
                if lock2 is not None:
                    lock2.release()

    def test_instance_lock_holds_file_reference(self) -> None:
        fake_file = type("F", (), {"close": lambda self: None})()
        lock = InstanceLock(fake_file)
        self.assertIsNotNone(lock._file)
        lock.release()
        self.assertIsNone(lock._file)


if __name__ == "__main__":
    unittest.main()
