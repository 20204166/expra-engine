import unittest
from pathlib import Path


class UrsinaIntegrationMapTest(unittest.TestCase):
    def test_audit_map_records_required_sources_and_safety_contracts(self) -> None:
        map_path = Path(__file__).parents[1] / "docs" / "URSINA_INTEGRATION_MAP.md"
        contents = map_path.read_text(encoding="utf-8")

        for required in (
            "Ursina 8.2.0",
            "MIT",
            "button.py",
            "nine_slice.py",
            "text_field.py",
            "input_handler.py",
            "mouse.py",
            "window.py",
            "tilemap.py",
            "build.py",
            "vec_field.py",
            "file_browser.py",
            "color_picker.py",
            "gradient_editor.py",
            "conversation.py",
            "hot_reloader.py",
            "Classification A",
            "Classification B",
            "Classification C",
            "Classification D",
            "Classification E",
            "no replaced Expra systems",
            "no Panda dependency",
            "no Tk game-runtime dependency",
        ):
            with self.subTest(required=required):
                self.assertIn(required, contents)

    def test_required_script_rows_record_audit_decisions(self) -> None:
        map_path = Path(__file__).parents[1] / "docs" / "URSINA_INTEGRATION_MAP.md"
        rows = map_path.read_text(encoding="utf-8").splitlines()

        required_rows = {
            "ursina/scripts/grid_layout.py": (
                "| B |",
                "ui_model/geometry.py",
                "empty",
                "max_x",
            ),
            "ursina/scripts/scrollable.py": (
                "| B |",
                "ui_model/controls.py",
                "hover",
                "clamp",
            ),
            "ursina/scripts/smooth_follow.py": (
                "| B |",
                "runtime/follow.py",
                "no target",
                "large delta",
            ),
        }
        for source, required in required_rows.items():
            with self.subTest(source=source):
                matching_rows = [row for row in rows if source in row]
                self.assertEqual(len(matching_rows), 1)
                for expected in required:
                    self.assertIn(expected, matching_rows[0])

    def test_audit_map_keeps_stable_section_structure(self) -> None:
        map_path = Path(__file__).parents[1] / "docs" / "URSINA_INTEGRATION_MAP.md"
        contents = map_path.read_text(encoding="utf-8")

        for heading in (
            "## Audit Scope",
            "## Non-Negotiable Answers",
            "## Expra Ownership Rules",
            "## Complete Neighbor Inventory",
            "## Approved Destinations And Test Matrix",
            "## Final Decision",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, contents)

    def test_task_12_records_implemented_destinations_and_boundaries(self) -> None:
        map_path = Path(__file__).parents[1] / "docs" / "URSINA_INTEGRATION_MAP.md"
        contents = map_path.read_text(encoding="utf-8")

        for required in (
            "core.safe_expression",
            "editor.safe_expression",
            "editor safe_expression re-export boundary",
            "runtime/input.py",
            "runtime/timeline.py",
            "runtime/animation.py",
            "runtime/follow.py",
            "runtime/tilemap.py",
            "runtime/dialogue.py",
            "editor/assets.py",
            "physical-input to semantic-action contract",
            "Update-driven scaled/unscaled timeline contract",
            "immutable sprite animation contract",
            "exponential 2D follow contract",
            "renderer-neutral tilemap contract",
            "typed dialogue graph contract",
            "async asset scan contract",
            "no Panda/Ursina/Tk game runtime",
            "existing release tooling remains the owner",
            "existing coordinator owners remain the owners",
            "controlled asset invalidation rather than exec",
            "window/display settings belong behind a platform backend",
            "dialogue presentation remains deferred",
            "color/gradient editing remains deferred",
            "radial menu remains deferred",
            "grid editor remains deferred",
            "mobile touch remains deferred",
            "renderer implementation remains deferred",
        ):
            with self.subTest(required=required):
                self.assertIn(required, contents)


if __name__ == "__main__":
    unittest.main()
