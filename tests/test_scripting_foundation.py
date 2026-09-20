"""Regression tests for the public scripting foundation."""

import json
import unittest
from typing import cast

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.runtime.behaviour import Behaviour, exposed
from expra_engine.runtime.script_component import ScriptComponent


class PlayerBehaviour(Behaviour):
    speed = exposed(160.0, min=0.0, max=500.0)
    health = exposed(100, min=0, max=100)

    def on_update(self, dt: float) -> None:
        transform = self.require_component(TransformComponent)
        if self.input.is_held("move_right"):
            transform.x += cast(float, self.speed) * dt


class BaseBehaviour(Behaviour):
    speed = exposed(10.0, min=0.0)
    mode = exposed("idle", choices=("idle", "run"))


class DerivedBehaviour(BaseBehaviour):
    speed = exposed(20.0, min=0.0, max=40.0)


class PropertyEdgeBehaviour(Behaviour):
    value = exposed(1.0)


class ScriptingFoundationTests(unittest.TestCase):
    def test_exposed_values_validate_without_partial_mutation(self) -> None:
        player = PlayerBehaviour()
        player.speed = 240.0
        self.assertEqual(player.speed, 240.0)
        with self.assertRaises(ValueError):
            player.speed = 999.0
        self.assertEqual(player.speed, 240.0)
        with self.assertRaises(TypeError):
            player.health = True

    def test_exposed_inheritance_and_non_finite_values_are_deterministic(self) -> None:
        schema = DerivedBehaviour.exposed_schema()
        self.assertEqual(schema["speed"].default, 20.0)
        self.assertEqual(schema["mode"].default, "idle")
        derived = DerivedBehaviour()
        with self.assertRaises(ValueError):
            derived.speed = float("nan")
        with self.assertRaises(ValueError):
            derived.mode = "attack"
        self.assertEqual(derived.speed, 20.0)
        with self.assertRaises(TypeError):
            exposed(None)
        with self.assertRaises(TypeError):
            exposed(object())

    def test_behaviour_context_exposes_entity_components_and_semantic_input(self) -> None:
        entity = Entity("Player")
        transform = TransformComponent()
        entity.add_component(transform)
        player = PlayerBehaviour()
        entity.add_behaviour(player, runtime_factory=PlayerBehaviour)
        player._bind_context(input_map=None, engine=None, scene=None)  # type: ignore[arg-type]
        self.assertIs(player.get_component(TransformComponent), transform)
        self.assertTrue(player.has_component(TransformComponent))
        self.assertIs(player.require_component(TransformComponent), transform)

    def test_script_component_round_trips_identity_values_and_order(self) -> None:
        component = ScriptComponent(
            "project://scripts/player.py",
            "PlayerBehaviour",
            enabled=False,
            exposed_values={"speed": 220.0, "health": 80},
            order=3,
        )
        entity = Entity("Player")
        entity.add_component(component)
        loaded = Scene.from_dict(json.loads(json.dumps(Scene("Level").to_dict())))
        self.assertEqual(loaded.entities, ())
        round_trip = ScriptComponent.from_dict(component.to_dict())
        self.assertEqual(str(round_trip.script_id), "project://scripts/player.py")
        self.assertEqual(round_trip.behaviour_class, "PlayerBehaviour")
        self.assertFalse(round_trip.enabled)
        self.assertEqual(round_trip.exposed_values["speed"], 220.0)
        self.assertEqual(round_trip.order, 3)

    def test_project_script_id_rejects_external_paths(self) -> None:
        from expra_engine.filesystem import ResourceId

        with self.assertRaises(ValueError):
            ResourceId.parse("project:///tmp/player.py")

    def test_invalid_script_metadata_survives_scene_load_for_repair(self) -> None:
        scene = Scene.from_dict(
            {
                "scene_id": "s",
                "name": "Level",
                "entities": [
                    {
                        "entity_id": "e",
                        "name": "Player",
                        "components": [
                            {
                                "type": "script",
                                "script_id": "../../escape.py",
                                "behaviour_class": "PlayerBehaviour",
                            }
                        ],
                    }
                ],
            }
        )
        component = scene.entities[0].components[0]
        self.assertEqual(component.to_dict()["script_id"], "../../escape.py")


if __name__ == "__main__":
    unittest.main()
