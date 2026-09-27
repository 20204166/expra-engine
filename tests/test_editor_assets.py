"""Contract tests for the backend-neutral asynchronous asset browser."""

from __future__ import annotations

import unittest
from pathlib import Path

from expra_engine.editor.assets import (
    AssetBrowserState,
    AssetEntry,
    AssetMode,
    AssetScanRequest,
    AssetScanResult,
    SaveDecision,
    accept_scan_result,
    build_save_decision,
    is_project_asset,
    iter_project_paths,
    normalize_entries,
    scan_directory,
)
from expra_engine.filesystem import ResourceId


class TestAssetNormalization(unittest.TestCase):
    def test_folders_first_then_case_insensitive_name(self) -> None:
        entries = normalize_entries(
            [
                AssetEntry(Path("zeta.png"), "zeta.png", False),
                AssetEntry(Path("Beta"), "Beta", True),
                AssetEntry(Path("alpha"), "alpha", True),
                AssetEntry(Path("Alpha.png"), "Alpha.png", False),
            ]
        )

        self.assertEqual(
            [entry.name for entry in entries], ["alpha", "Beta", "Alpha.png", "zeta.png"]
        )

    def test_filter_matches_names_and_keeps_folders_visible(self) -> None:
        entries = normalize_entries(
            [
                AssetEntry(Path("sprites"), "sprites", True),
                AssetEntry(Path("hero.png"), "hero.png", False),
                AssetEntry(Path("readme.txt"), "readme.txt", False),
            ],
            filter_text="png",
        )

        self.assertEqual([entry.name for entry in entries], ["sprites", "hero.png"])

    def test_empty_results_are_normalized(self) -> None:
        self.assertEqual(normalize_entries([], filter_text="missing"), ())

    def test_entry_keeps_display_path_and_logical_id(self) -> None:
        path = Path("/project/assets/hero.png")
        entry = AssetEntry(path, "hero.png", False, ResourceId.parse("assets://hero.png"))

        self.assertEqual(entry.path, path)
        self.assertEqual(entry.display_path, path)
        self.assertEqual(entry.logical_id, ResourceId.parse("assets://hero.png"))

    def test_audio_assets_are_registered_as_audio_entries(self) -> None:
        self.assertEqual(AssetEntry(Path("theme.ogg"), "theme.ogg", False).kind, "Audio")
        self.assertEqual(AssetEntry(Path("theme.wav"), "theme.wav", False).kind, "Audio")

    def test_image_assets_are_registered_as_image_entries(self) -> None:
        self.assertEqual(AssetEntry(Path("hero.png"), "hero.png", False).kind, "Image")
        self.assertEqual(AssetEntry(Path("hero.jpg"), "hero.jpg", False).kind, "Image")

    def test_scene_files_under_scenes_are_registered_as_scene_entries(self) -> None:
        entry = AssetEntry(
            Path("/proj/scenes/room.json"),
            "room.json",
            False,
            ResourceId.from_project_path("scenes/room.json", scheme="project"),
        )
        self.assertEqual(entry.kind, "Scene")

    def test_project_manifest_is_not_a_scene_entry(self) -> None:
        entry = AssetEntry(
            Path("/proj/project.json"),
            "project.json",
            False,
            ResourceId.from_project_path("project.json", scheme="project"),
        )
        self.assertEqual(entry.kind, "Project")

    def test_typed_pb_documents_are_not_generic_files(self) -> None:
        self.assertEqual(
            AssetEntry(
                Path("/proj/levels/deepcore.level.pb"),
                "deepcore.level.pb",
                False,
                ResourceId.from_project_path("levels/deepcore.level.pb", scheme="project"),
            ).kind,
            "Level",
        )
        self.assertEqual(
            AssetEntry(
                Path("/proj/scenes/security_door.scene.pb"),
                "security_door.scene.pb",
                False,
                ResourceId.from_project_path("scenes/security_door.scene.pb", scheme="project"),
            ).kind,
            "Scene",
        )
        self.assertEqual(
            AssetEntry(
                Path("/proj/worlds/main.world.pb"),
                "main.world.pb",
                False,
                ResourceId.from_project_path("worlds/main.world.pb", scheme="project"),
            ).kind,
            "World",
        )

    def test_typed_project_documents_and_scripts_have_canonical_labels(self) -> None:
        self.assertEqual(
            AssetEntry(
                Path("/proj/levels/main.level.json"),
                "main.level.json",
                False,
                ResourceId.from_project_path("levels/main.level.json", scheme="project"),
            ).kind,
            "Level",
        )
        self.assertEqual(
            AssetEntry(
                Path("/proj/scenes/room.scene.json"),
                "room.scene.json",
                False,
                ResourceId.from_project_path("scenes/room.scene.json", scheme="project"),
            ).kind,
            "Scene",
        )
        self.assertEqual(
            AssetEntry(
                Path("/proj/project.json"),
                "project.json",
                False,
                ResourceId.from_project_path("project.json", scheme="project"),
            ).kind,
            "Project",
        )
        self.assertEqual(AssetEntry(Path("game.py"), "game.py", False).kind, "Script")


class TestAssetBrowserState(unittest.TestCase):
    def test_selection_and_folder_navigation_update_display_path(self) -> None:
        state = AssetBrowserState(Path("/project/assets"))
        folder = AssetEntry(Path("/project/assets/sprites"), "sprites", True)
        image = AssetEntry(Path("/project/assets/hero.png"), "hero.png", False)

        self.assertEqual(state.display_path, Path("/project/assets"))
        state.select(image)
        self.assertEqual(state.display_path, image.path)
        state.navigate(folder)
        self.assertEqual(state.current_directory, folder.path)
        self.assertIsNone(state.selected)
        self.assertEqual(state.display_path, folder.path)

    def test_open_mode_does_not_accept_a_folder_as_file_selection(self) -> None:
        state = AssetBrowserState(Path("/project/assets"), mode=AssetMode.OPEN)
        folder = AssetEntry(Path("/project/assets/sprites"), "sprites", True)

        self.assertFalse(state.can_submit(folder))
        state.navigate(folder)
        self.assertFalse(state.can_submit(None))

    def test_save_mode_accepts_a_filename_and_rejects_blank_names(self) -> None:
        state = AssetBrowserState(Path("/project/assets"), mode=AssetMode.SAVE)

        self.assertTrue(state.can_submit("level.json"))
        self.assertFalse(state.can_submit("  "))


class TestAssetRequestsAndResults(unittest.TestCase):
    def test_request_carries_mode_filter_and_generation(self) -> None:
        request = AssetScanRequest(
            Path("/project/assets"), generation=7, mode=AssetMode.SAVE, filter_text="png"
        )

        self.assertEqual(request.generation, 7)
        self.assertEqual(request.mode, AssetMode.SAVE)
        self.assertEqual(request.filter_text, "png")

    def test_scan_uses_injected_enumerator_and_reports_missing_folder(self) -> None:
        request = AssetScanRequest(Path("/missing"), generation=2)
        calls: list[Path] = []

        def enumerate_directory(path: Path) -> list[Path]:
            calls.append(path)
            raise FileNotFoundError(path)

        result = scan_directory(request, enumerate_directory)

        self.assertEqual(calls, [Path("/missing")])
        self.assertEqual(result.entries, ())
        self.assertEqual(result.error, "folder-missing")

    def test_scan_assigns_project_relative_logical_ids(self) -> None:
        root = Path("/project/assets")
        request = AssetScanRequest(root, generation=1, resource_root=root)

        result = scan_directory(request, lambda _path: [root / "textures" / "hero.png"])

        self.assertEqual(result.entries[0].path, root / "textures" / "hero.png")
        self.assertEqual(
            result.entries[0].logical_id, ResourceId.parse("assets://textures/hero.png")
        )

    def test_scan_reports_permission_error(self) -> None:
        request = AssetScanRequest(Path("/private"), generation=3)

        def enumerate_directory(_path: Path) -> list[Path]:
            raise PermissionError("denied")

        result = scan_directory(request, enumerate_directory)

        self.assertEqual(result.error, "folder-permission")

    def test_cancelled_scan_has_no_entries(self) -> None:
        request = AssetScanRequest(Path("/project/assets"), generation=4, cancelled=True)
        result = scan_directory(request, lambda _path: [Path("hero.png")])

        self.assertTrue(result.cancelled)
        self.assertEqual(result.entries, ())

    def test_stale_generation_is_rejected(self) -> None:
        result = AssetScanResult(directory=Path("/project/assets"), generation=4, entries=())

        self.assertFalse(accept_scan_result(result, current_generation=5))
        self.assertTrue(accept_scan_result(result, current_generation=4))


class TestSaveDecisions(unittest.TestCase):
    def test_existing_target_requires_confirmation(self) -> None:
        decision = build_save_decision(Path("/project/assets/level.json"), exists=True)

        self.assertEqual(decision, SaveDecision.CONFIRM_OVERWRITE)

    def test_confirmed_existing_target_is_submittable(self) -> None:
        decision = build_save_decision(
            Path("/project/assets/level.json"), exists=True, overwrite_confirmed=True
        )

        self.assertEqual(decision, SaveDecision.SUBMIT)

    def test_cancelled_save_is_not_submittable(self) -> None:
        decision = build_save_decision(
            Path("/project/assets/level.json"), exists=False, cancelled=True
        )

        self.assertEqual(decision, SaveDecision.CANCELLED)


class TestIsProjectAsset(unittest.TestCase):
    """Unit tests for the canonical is_project_asset filter.

    ``is_dir`` is passed explicitly so no real filesystem is required.
    """

    # --- ignored directories ---

    def test_pycache_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("__pycache__"), is_dir=True))

    def test_pytest_cache_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".pytest_cache"), is_dir=True))

    def test_mypy_cache_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".mypy_cache"), is_dir=True))

    def test_ruff_cache_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".ruff_cache"), is_dir=True))

    def test_git_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".git"), is_dir=True))

    def test_venv_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".venv"), is_dir=True))
        self.assertFalse(is_project_asset(Path("venv"), is_dir=True))

    def test_idea_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".idea"), is_dir=True))

    def test_vscode_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".vscode"), is_dir=True))

    def test_node_modules_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("node_modules"), is_dir=True))

    def test_htmlcov_dir_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("htmlcov"), is_dir=True))

    # --- ignored files ---

    def test_pyc_file_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("player.cpython-312.pyc"), is_dir=False))

    def test_pyo_file_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("module.pyo"), is_dir=False))

    def test_ds_store_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".DS_Store"), is_dir=False))

    def test_thumbs_db_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("Thumbs.db"), is_dir=False))

    def test_desktop_ini_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("desktop.ini"), is_dir=False))

    def test_vim_swap_files_are_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("player.py.swp"), is_dir=False))
        self.assertFalse(is_project_asset(Path("player.py.swo"), is_dir=False))

    def test_tilde_backup_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("notes.txt~"), is_dir=False))

    def test_tmp_file_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path("upload.tmp"), is_dir=False))

    def test_coverage_data_file_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".coverage"), is_dir=False))

    def test_coverage_variant_file_is_excluded(self) -> None:
        self.assertFalse(is_project_asset(Path(".coverage.hostname.1234.abc"), is_dir=False))

    # --- legitimate project assets remain visible ---

    def test_python_script_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("player.py"), is_dir=False))

    def test_scene_pb_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("room.scene.pb"), is_dir=False))

    def test_level_pb_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("forest.level.pb"), is_dir=False))

    def test_world_pb_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("main.world.pb"), is_dir=False))

    def test_image_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("hero.png"), is_dir=False))

    def test_audio_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("theme.ogg"), is_dir=False))

    def test_project_json_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("project.json"), is_dir=False))

    def test_notes_txt_is_included(self) -> None:
        self.assertTrue(is_project_asset(Path("notes.txt"), is_dir=False))

    def test_legitimate_dirs_are_included(self) -> None:
        for name in ("scripts", "scenes", "levels", "worlds", "assets", "tests", "docs", "tools"):
            self.assertTrue(
                is_project_asset(Path(name), is_dir=True), f"expected {name} to be included"
            )

    def test_cache_in_filename_not_confused_with_cache_dir(self) -> None:
        # "cache_room.level.pb" is a legitimate level name
        self.assertTrue(is_project_asset(Path("cache_room.level.pb"), is_dir=False))
        self.assertTrue(is_project_asset(Path("cache_machine.scene.pb"), is_dir=False))


import tempfile  # noqa: E402  (below existing imports for cohesion with test class)


class TestIterProjectPaths(unittest.TestCase):
    """Integration tests for iter_project_paths against a real synthetic tree."""

    def _make(self, root: Path, layout: dict) -> None:
        for name, content in layout.items():
            path = root / name
            if isinstance(content, dict):
                path.mkdir(parents=True, exist_ok=True)
                self._make(path, content)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content or "x")

    def test_legitimate_project_content_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make(
                root,
                {
                    "project.json": "{}",
                    "worlds": {"main.world.pb": ""},
                    "levels": {"town.level.pb": ""},
                    "scenes": {"door.scene.pb": ""},
                    "scripts": {"player.py": ""},
                    "assets": {"hero.png": ""},
                    "audio": {"theme.ogg": ""},
                },
            )

            paths = iter_project_paths(root)
            names = {p.name for p in paths}

            self.assertIn("project.json", names)
            self.assertIn("worlds", names)
            self.assertIn("main.world.pb", names)
            self.assertIn("levels", names)
            self.assertIn("town.level.pb", names)
            self.assertIn("scenes", names)
            self.assertIn("door.scene.pb", names)
            self.assertIn("scripts", names)
            self.assertIn("player.py", names)
            self.assertIn("assets", names)
            self.assertIn("hero.png", names)
            self.assertIn("audio", names)
            self.assertIn("theme.ogg", names)

    def test_pycache_and_pytest_cache_are_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make(
                root,
                {
                    "scripts": {"player.py": ""},
                    "__pycache__": {"player.cpython-312.pyc": ""},
                    "scripts/__pycache__": {"player.cpython-312.pyc": ""},
                    ".pytest_cache": {"v": {"cache": {"lastfailed": ""}}},
                    ".ruff_cache": {"0.1": {}},
                    ".mypy_cache": {"3.12": {}},
                },
            )

            paths = iter_project_paths(root)
            names = {p.name for p in paths}

            self.assertNotIn("__pycache__", names)
            self.assertNotIn(".pytest_cache", names)
            self.assertNotIn(".ruff_cache", names)
            self.assertNotIn(".mypy_cache", names)
            self.assertNotIn("player.cpython-312.pyc", names)
            self.assertIn("scripts", names)
            self.assertIn("player.py", names)

    def test_ignored_files_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make(
                root,
                {
                    "scripts": {"player.py": ""},
                    ".DS_Store": "",
                    "Thumbs.db": "",
                    "desktop.ini": "",
                    "notes.txt~": "",
                    "upload.tmp": "",
                    ".coverage": "",
                    ".coverage.host.1234.abc": "",
                    "build_artifact.pyc": "",
                },
            )

            paths = iter_project_paths(root)
            names = {p.name for p in paths}

            self.assertNotIn(".DS_Store", names)
            self.assertNotIn("Thumbs.db", names)
            self.assertNotIn("desktop.ini", names)
            self.assertNotIn("notes.txt~", names)
            self.assertNotIn("upload.tmp", names)
            self.assertNotIn(".coverage", names)
            self.assertNotIn(".coverage.host.1234.abc", names)
            self.assertNotIn("build_artifact.pyc", names)
            self.assertIn("scripts", names)
            self.assertIn("player.py", names)

    def test_deep_cache_is_pruned_regardless_of_depth(self) -> None:
        """Cache directories at any depth must not be visited."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make(
                root,
                {
                    "assets": {
                        "a": {
                            "b": {
                                "c": {
                                    "__pycache__": {"deep.cpython-312.pyc": ""},
                                    "texture.png": "",
                                }
                            }
                        }
                    }
                },
            )

            paths = iter_project_paths(root)
            names = {p.name for p in paths}

            self.assertNotIn("__pycache__", names)
            self.assertNotIn("deep.cpython-312.pyc", names)
            self.assertIn("texture.png", names)

    def test_git_dir_is_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make(
                root,
                {
                    "project.json": "{}",
                    ".git": {"HEAD": "ref: refs/heads/main", "config": ""},
                },
            )

            paths = iter_project_paths(root)
            names = {p.name for p in paths}

            self.assertNotIn(".git", names)
            self.assertNotIn("HEAD", names)
            self.assertIn("project.json", names)

    def test_venv_is_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make(
                root,
                {
                    "project.json": "{}",
                    ".venv": {"pyvenv.cfg": "", "lib": {"python3.12": {"site-packages": {}}}},
                    "venv": {"pyvenv.cfg": "", "bin": {"python": ""}},
                },
            )

            paths = iter_project_paths(root)
            names = {p.name for p in paths}

            self.assertNotIn(".venv", names)
            self.assertNotIn("venv", names)
            self.assertNotIn("pyvenv.cfg", names)
            self.assertIn("project.json", names)

    def test_cache_name_in_legitimate_file_not_pruned(self) -> None:
        """Filenames containing 'cache' are not affected by the directory prune rule."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make(
                root,
                {
                    "levels": {
                        "cache_room.level.pb": "",
                        "cache_terminal.level.pb": "",
                    },
                },
            )

            paths = iter_project_paths(root)
            names = {p.name for p in paths}

            self.assertIn("cache_room.level.pb", names)
            self.assertIn("cache_terminal.level.pb", names)

    def test_empty_directory_returns_no_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(iter_project_paths(Path(tmp)), ())

    def test_missing_directory_returns_no_paths(self) -> None:
        self.assertEqual(iter_project_paths(Path("/nonexistent/project/root")), ())


if __name__ == "__main__":
    unittest.main()
