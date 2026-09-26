"""Tests for the Level document type and document-kind classification."""

from __future__ import annotations

import json
import unittest

from expra_engine.core.component import TransformComponent
from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene import Level, LevelMetadata, Scene


class DocumentKindTests(unittest.TestCase):
    def test_kind_values(self) -> None:
        self.assertEqual(DocumentKind.SCENE.value, "scene")
        self.assertEqual(DocumentKind.LEVEL.value, "level")


class LevelTests(unittest.TestCase):
    def test_level_is_a_scene_with_level_kind(self) -> None:
        level = Level("Main")
        self.assertIsInstance(level, Scene)
        self.assertEqual(level.document_kind, DocumentKind.LEVEL)
        self.assertEqual(Scene("Plain").document_kind, DocumentKind.SCENE)

    def test_level_round_trips_entities_and_metadata(self) -> None:
        level = Level(
            "Deepcore",
            scene_id="level-1",
            level_metadata=LevelMetadata(
                display_name="Deepcore Facility",
                world_bounds=(-20.0, -10.0, 40.0, 30.0),
                spawn_entity_id="player",
                default_camera_id="cam",
                tags=("indoor", "arena"),
            ),
        )
        player = level.create_entity("Player", entity_id="player")
        player.add_component(TransformComponent(x=1.0, y=2.0))
        wall = level.create_entity("Wall", parent_id="player")

        restored = Level.from_dict(json.loads(json.dumps(level.to_dict())))

        self.assertIsInstance(restored, Level)
        self.assertEqual(restored.scene_id, "level-1")
        self.assertEqual(restored.name, "Deepcore")
        self.assertEqual(
            {entity.entity_id for entity in restored.entities}, {"player", wall.entity_id}
        )
        self.assertIsNotNone(restored.find_entity("player"))
        self.assertEqual(restored.level_metadata.display_name, "Deepcore Facility")
        self.assertEqual(restored.level_metadata.world_bounds, (-20.0, -10.0, 40.0, 30.0))
        self.assertEqual(restored.level_metadata.spawn_entity_id, "player")
        self.assertEqual(restored.level_metadata.tags, ("indoor", "arena"))

    def test_level_to_dict_marks_kind_and_metadata(self) -> None:
        level = Level("Cell", level_metadata=LevelMetadata(display_name="Test Cell"))
        data = level.to_dict()
        self.assertEqual(data["kind"], "level")
        self.assertEqual(data["level_metadata"]["display_name"], "Test Cell")

    def test_plain_scene_to_dict_has_no_kind_field(self) -> None:
        self.assertNotIn("kind", Scene("Plain").to_dict())


if __name__ == "__main__":
    unittest.main()
