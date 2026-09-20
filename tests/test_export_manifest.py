"""Tests for AssetManifest and BuildManifest."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from expra_engine.export.manifest import (
    AssetManifest,
    BuildManifest,
    ASSET_IGNORE_DIRS,
    ASSET_IGNORE_SUFFIXES,
)


class TestAssetManifest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())

    def _create_files(self, *names: str) -> None:
        for name in names:
            f = self._tmp / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(name.encode())

    def test_collects_files(self) -> None:
        self._create_files("a.txt", "b.png", "sub/c.wav")
        manifest = AssetManifest.collect(self._tmp)
        paths = {e.path for e in manifest.entries}
        self.assertEqual(paths, {"a.txt", "b.png", "sub/c.wav"})

    def test_excludes_pycache(self) -> None:
        self._create_files("game.txt", "__pycache__/foo.pyc")
        manifest = AssetManifest.collect(self._tmp)
        paths = {e.path for e in manifest.entries}
        self.assertIn("game.txt", paths)
        self.assertNotIn("__pycache__/foo.pyc", paths)

    def test_excludes_git(self) -> None:
        self._create_files("game.txt", ".git/config")
        manifest = AssetManifest.collect(self._tmp)
        self.assertNotIn(".git/config", {e.path for e in manifest.entries})

    def test_excludes_psd_suffix(self) -> None:
        self._create_files("art.psd", "sprite.png")
        manifest = AssetManifest.collect(self._tmp)
        paths = {e.path for e in manifest.entries}
        self.assertNotIn("art.psd", paths)
        self.assertIn("sprite.png", paths)

    def test_extra_exclude_patterns(self) -> None:
        self._create_files("keep.txt", "skip.txt")
        manifest = AssetManifest.collect(self._tmp, extra_exclude_patterns=frozenset({"skip.txt"}))
        paths = {e.path for e in manifest.entries}
        self.assertIn("keep.txt", paths)
        self.assertNotIn("skip.txt", paths)

    def test_sha256_is_hex(self) -> None:
        self._create_files("file.txt")
        manifest = AssetManifest.collect(self._tmp)
        sha = manifest.entries[0].sha256
        self.assertEqual(len(sha), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in sha))

    def test_size_matches(self) -> None:
        (self._tmp / "hello.txt").write_text("hello world")
        manifest = AssetManifest.collect(self._tmp)
        entry = manifest.entries[0]
        self.assertEqual(entry.size, 11)

    def test_to_json_round_trip(self) -> None:
        self._create_files("a.txt", "b.dat")
        manifest = AssetManifest.collect(self._tmp)
        restored = AssetManifest.from_json(manifest.to_json())
        self.assertEqual(
            [e.path for e in manifest.entries],
            [e.path for e in restored.entries],
        )

    def test_entries_sorted(self) -> None:
        self._create_files("z.txt", "a.txt", "m.txt")
        manifest = AssetManifest.collect(self._tmp)
        paths = [e.path for e in manifest.entries]
        self.assertEqual(paths, sorted(paths))

    def test_empty_directory(self) -> None:
        manifest = AssetManifest.collect(self._tmp)
        self.assertEqual(manifest.entries, [])

    def test_include_source_false_excludes_py(self) -> None:
        self._create_files("game.py", "sprite.png")
        manifest = AssetManifest.collect(self._tmp, include_source=False)
        paths = {e.path for e in manifest.entries}
        self.assertNotIn("game.py", paths)
        self.assertIn("sprite.png", paths)


class TestBuildManifest(unittest.TestCase):
    def _manifest(self, **overrides: object) -> BuildManifest:
        defaults: dict = dict(
            game_name="Test Game",
            game_version="1.2.3",
            engine_version="0.1.7.1",
            target="windows",
            python_version="3.12.4",
            arch="amd64",
            compile_bytecode=True,
            entry_point="__main__.py",
            build_timestamp="2026-09-20T00:00:00+00:00",
        )
        defaults.update(overrides)
        return BuildManifest(**defaults)  # type: ignore[arg-type]

    def test_to_json_round_trip(self) -> None:
        m = self._manifest()
        restored = BuildManifest.from_json(m.to_json())
        self.assertEqual(restored.game_name, "Test Game")
        self.assertEqual(restored.compile_bytecode, True)

    def test_json_has_required_keys(self) -> None:
        data = json.loads(self._manifest().to_json())
        for key in ("game_name", "game_version", "engine_version", "target", "entry_point"):
            self.assertIn(key, data)

    def test_frozen(self) -> None:
        m = self._manifest()
        with self.assertRaises((AttributeError, TypeError)):
            m.game_name = "Other"  # type: ignore[misc]
