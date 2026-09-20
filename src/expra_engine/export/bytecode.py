"""Bytecode compiler: .py -> .pyc (in-place in a build directory)."""

from __future__ import annotations

import py_compile
import threading
from collections.abc import Callable
from pathlib import Path

_SKIP_DIRS: frozenset[str] = frozenset({"__pycache__", ".git"})


class BytecodeCompiler:
    """Compile .py files to .pyc in-place in a build directory."""

    def compile(
        self,
        source_dir: Path,
        dest_dir: Path,
        *,
        cancel: threading.Event,
        progress: Callable[[str], None],
        skip_dirs: frozenset[str] = _SKIP_DIRS,
    ) -> int:
        """Compile all .py files under source_dir into dest_dir.

        Returns the number of files compiled.
        Raises RuntimeError on the first py_compile failure.
        """
        compiled = 0
        for py_file in sorted(source_dir.rglob("*.py")):
            if cancel.is_set():
                return compiled
            rel = py_file.relative_to(source_dir)
            if any(part in skip_dirs for part in rel.parts):
                continue
            dest_pyc = dest_dir / rel.with_suffix(".pyc")
            dest_pyc.parent.mkdir(parents=True, exist_ok=True)
            try:
                py_compile.compile(str(py_file), str(dest_pyc), doraise=True)
            except py_compile.PyCompileError as e:
                raise RuntimeError(f"Bytecode compile error in {rel}: {e}") from e
            compiled += 1
            progress(f"Compiled {rel}")
        return compiled
