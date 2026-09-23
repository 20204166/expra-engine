"""Read-only access layer for the six source roots: expra + the five
reference repos (godot, ppb, minipy, ursina, exp_ui).

Reference roots are permanently read-only regardless of what config claims
(spec section 12) -- callers never get a write path for them because this
module never exposes one, not because a flag says so.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .config import ExpraMcpConfig

DEFAULT_EXCLUDE_DIR_NAMES = frozenset(
    {
        ".git",
        "build",
        "dist",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".expra-mcp",
        ".egg-info",
    }
)

BINARY_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz",
        ".wav", ".mp3", ".ogg", ".flac",
        ".ttf", ".otf", ".woff", ".woff2",
        ".zip", ".whl", ".tar", ".gz", ".7z", ".xz",
        ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".a", ".o", ".obj",
        ".pdf", ".db", ".sqlite", ".sqlite3",
    }
)

_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".h": "c",
    ".c": "c",
    ".cs": "csharp",
    ".gd": "gdscript",
    ".tscn": "godot-scene",
    ".tres": "godot-resource",
    ".js": "javascript",
    ".ts": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".md": "markdown",
    ".toml": "toml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".cfg": "ini",
    ".ini": "ini",
    ".txt": "text",
}


class SourceAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceRoot:
    id: str
    path: Path
    read_only: bool
    domains: tuple[str, ...] = ()


def resolve_roots(cfg: ExpraMcpConfig) -> dict[str, SourceRoot]:
    roots: dict[str, SourceRoot] = {
        "expra": SourceRoot(id="expra", path=cfg.workspace.expra_root, read_only=False, domains=())
    }
    for ref_id, ref in cfg.references.items():
        roots[ref_id] = SourceRoot(id=ref_id, path=ref.path, read_only=True, domains=tuple(ref.domains))
    return roots


def get_root(cfg: ExpraMcpConfig, repo: str) -> SourceRoot:
    roots = resolve_roots(cfg)
    if repo not in roots:
        raise SourceAccessError(f"unknown source id {repo!r} (known: {', '.join(sorted(roots))})")
    return roots[repo]


def resolve_relative_path(root: SourceRoot, relative_path: str) -> Path:
    """Enforce containment: reject NUL bytes, absolute paths, and any
    resolved (symlink-following) escape from ``root``.
    """

    if "\x00" in relative_path:
        raise SourceAccessError("path contains a NUL byte")
    raw = Path(relative_path)
    if raw.is_absolute():
        raise SourceAccessError(f"absolute paths are not allowed: {relative_path!r}")
    candidate = (root.path / raw).resolve()
    if not paths.is_contained(candidate, root.path):
        raise SourceAccessError(f"path escapes the {root.id!r} root: {relative_path!r}")
    return candidate


def is_probably_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    try:
        with path.open("rb") as fh:
            chunk = fh.read(4096)
    except OSError:
        return True
    return b"\x00" in chunk


def guess_language(relative_path: str) -> str | None:
    return _LANGUAGE_BY_SUFFIX.get(Path(relative_path).suffix.lower())


def iter_source_files(
    root: SourceRoot,
    *,
    path_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
):
    """Yield candidate files under ``root``, pruning excluded directories
    during the walk (not just filtering after) so this stays fast on large
    trees like the local Godot checkout.
    """

    import fnmatch

    for dirpath, dirnames, filenames in os.walk(root.path):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIR_NAMES]
        for filename in filenames:
            file_path = Path(dirpath) / filename
            rel = file_path.relative_to(root.path).as_posix()
            if exclude_globs and any(fnmatch.fnmatch(rel, pattern) for pattern in exclude_globs):
                continue
            if path_globs and not any(fnmatch.fnmatch(rel, pattern) for pattern in path_globs):
                continue
            yield file_path
