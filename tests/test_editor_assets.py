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
    normalize_entries,
    scan_directory,
)


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


if __name__ == "__main__":
    unittest.main()
