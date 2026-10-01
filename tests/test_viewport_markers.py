"""Level anchor markers are visibly named in the Level authoring viewport."""

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Level
from expra_engine.runtime.level_anchor import LevelAnchorComponent
from expra_engine.ui.viewport_markers import draw_entity_markers


class RecordingCanvas:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, object]]] = []

    def create_rectangle(self, *args, **kwargs) -> int:
        self.created.append(("rectangle", kwargs))
        return len(self.created)

    def create_text(self, *args, **kwargs) -> int:
        self.created.append(("text", kwargs))
        return len(self.created)

    def delete(self, _tag) -> None:
        pass


class Camera:
    @staticmethod
    def project(point):
        return point


def test_named_exit_anchor_draws_its_id_and_kind_even_on_a_visual_entity() -> None:
    level = Level("Town")
    gate = level.create_entity("East Gate")
    gate.add_component(TransformComponent(x=12.0, y=3.0))
    gate.add_component(LevelAnchorComponent("east_gate", kind="exit", size=(6.0, 8.0)))
    canvas = RecordingCanvas()

    draw_entity_markers(
        canvas,
        {"surface": "#fff", "ink_2": "#111", "ink_3": "#333", "accent": "#0ff", "accent_ink": "#000", "warning": "#fa0", "success": "#0a0", "camera": "#08f", "camera_active": "#0ff", "player": "#f00", "player_active": "#0f0"},
        level,
        {gate.entity_id},
        None,
        Camera(),
        {},
    )

    labels = [options["text"] for kind, options in canvas.created if kind == "text"]
    assert labels == ["East Gate\neast_gate · exit\n6 x 8"]


def test_marker_projection_does_not_scan_components_when_transform_exists(monkeypatch) -> None:
    scene = Level("Markers")
    entity = scene.create_entity("Decorated")
    entity.add_component(TransformComponent(x=2.0, y=3.0))
    entity.add_component(LevelAnchorComponent("door", kind="entrance"))
    component_reads = 0
    original_components = Entity.components.fget
    assert original_components is not None

    def counted_components(owner):
        nonlocal component_reads
        component_reads += 1
        return original_components(owner)

    monkeypatch.setattr(Entity, "components", property(counted_components))

    draw_entity_markers(
        RecordingCanvas(),
        {
            "surface": "#fff",
            "ink_2": "#111",
            "ink_3": "#333",
            "accent": "#0ff",
            "accent_ink": "#000",
            "warning": "#fa0",
            "success": "#0a0",
            "camera": "#08f",
            "camera_active": "#0ff",
            "player": "#f00",
            "player_active": "#0f0",
        },
        scene,
        set(),
        None,
        Camera(),
        {},
    )

    assert component_reads == 0
