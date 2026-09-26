"""Production-path document loading observability coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from expra_engine.core.component import TransformComponent
from expra_engine.core.project import Project, ProjectError
from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.observability import MetricSnapshot, ObservabilityWatcher


def _metric_map(observer: ObservabilityWatcher) -> dict[str, MetricSnapshot]:
    return {metric.target: metric for metric in observer.snapshot().metrics}


class DocumentObservabilityTests(unittest.TestCase):
    def test_protobuf_load_records_stable_stage_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Project.create("Observed", Path(directory) / "project")
            scene = Scene("Observed Scene", scene_id="observed-scene")
            scene.create_entity("Entity").add_component(TransformComponent(x=2.0))
            project.save_document(scene, "scenes/observed.scene.pb")
            observer = ObservabilityWatcher()

            loaded = project.load_document("scenes/observed.scene.pb", observer=observer)

            self.assertEqual(loaded.scene_id, "observed-scene")
            metrics = _metric_map(observer)
            self.assertEqual(
                set(metrics),
                {
                    "document:read",
                    "document:decode",
                    "document:convert",
                    "document:construct",
                    "document:construct:entities",
                    "document:construct:components",
                    "document:construct:hierarchy",
                    "scene:resolve_instances",
                    "document:load",
                },
            )
            self.assertTrue(all(metric.count == 1 for metric in metrics.values()))
            self.assertTrue(all(metric.in_flight == 0 for metric in metrics.values()))

    def test_legacy_json_load_has_no_fake_protobuf_conversion_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Project.create("Observed", Path(directory) / "project")
            scene = Scene("Legacy Scene", scene_id="legacy-scene")
            project.save_scene(scene, "scenes/legacy.json")
            observer = ObservabilityWatcher()

            project.load_document("scenes/legacy.json", observer=observer)

            metrics = _metric_map(observer)
            self.assertNotIn("document:convert", metrics)
            self.assertEqual(metrics["document:decode"].count, 1)
            self.assertEqual(metrics["document:construct"].count, 1)

    def test_construction_records_aggregate_substages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Project.create("Observed", Path(directory) / "project")
            scene = Scene("Observed Scene", scene_id="observed-scene")
            entity = scene.create_entity("Entity")
            entity.add_component(TransformComponent(x=2.0))
            project.save_document(scene, "scenes/observed.scene.pb")
            observer = ObservabilityWatcher()

            project.load_document("scenes/observed.scene.pb", observer=observer)

            metrics = _metric_map(observer)
            for target in (
                "document:construct:entities",
                "document:construct:components",
                "document:construct:hierarchy",
            ):
                assert metrics[target].count == 1
                assert metrics[target].in_flight == 0

    def test_nested_scene_instance_loads_reuse_the_same_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Project.create("Observed", Path(directory) / "project")
            source = Scene("Source", scene_id="source")
            source.create_entity("Source Entity")
            project.save_document(source, "scenes/source.scene.pb")
            owner = Scene("Owner", scene_id="owner")
            instance = owner.create_entity("Instance")
            instance.add_component(SceneInstanceComponent("scenes/source.scene.pb"))
            project.save_document(owner, "scenes/owner.scene.pb")
            observer = ObservabilityWatcher()

            project.load_document("scenes/owner.scene.pb", observer=observer)

            metrics = _metric_map(observer)
            for target in (
                "document:read",
                "document:decode",
                "document:convert",
                "document:construct",
                "scene:resolve_instances",
                "document:load",
            ):
                self.assertEqual(metrics[target].count, 2, target)
                self.assertEqual(metrics[target].in_flight, 0, target)

    def test_decode_failure_records_stage_and_total_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Project.create("Observed", Path(directory) / "project")
            path = project.path / "scenes" / "broken.scene.pb"
            path.write_bytes(b"not protobuf")
            project.register_scene_path("scenes/broken.scene.pb")
            observer = ObservabilityWatcher()

            with self.assertRaises(ProjectError):
                project.load_document("scenes/broken.scene.pb", observer=observer)

            metrics = _metric_map(observer)
            self.assertEqual(metrics["document:decode"].failures, 1)
            self.assertEqual(metrics["document:load"].failures, 1)
            self.assertEqual(metrics["document:decode"].in_flight, 0)
            self.assertEqual(metrics["document:load"].in_flight, 0)

    def test_many_resources_keep_targets_and_samples_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Project.create("Observed", Path(directory) / "project")
            for index in range(100):
                project.save_document(
                    Scene(f"Scene {index}", scene_id=f"scene-{index}"),
                    f"scenes/document-{index}.scene.pb",
                )
            project.save()
            observer = ObservabilityWatcher(sample_limit=8)

            for index in range(100):
                project.load_document(f"scenes/document-{index}.scene.pb", observer=observer)
            for _ in range(200):
                project.load_document("scenes/document-0.scene.pb", observer=observer)

            snapshot = observer.snapshot()
            self.assertEqual(len(snapshot.metrics), 9)
            self.assertEqual(
                next(
                    metric.count for metric in snapshot.metrics if metric.target == "document:load"
                ),
                300,
            )
            self.assertLessEqual(max(len(metric.samples) for metric in snapshot.metrics), 8)
            self.assertTrue(all(metric.in_flight == 0 for metric in snapshot.metrics))


if __name__ == "__main__":
    unittest.main()
