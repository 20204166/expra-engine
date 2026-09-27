from __future__ import annotations

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.scene import Scene
from expra_engine.ui.viewport_camera import ViewportCamera
from expra_engine.ui.viewport_lighting import update_light_gizmo


class RecordingCanvas:
    def __init__(self) -> None:
        self.next_id = 0
        self.created: list[tuple[str, int]] = []
        self.coordinates: dict[int, tuple[float, ...]] = {}
        self.deleted: list[int] = []

    def _create(self, kind: str) -> int:
        self.next_id += 1
        self.created.append((kind, self.next_id))
        return self.next_id

    def create_oval(self, *coordinates, **_options) -> int:
        item_id = self._create("oval")
        self.coordinates[item_id] = tuple(coordinates)
        return item_id

    def create_line(self, *coordinates, **_options) -> int:
        item_id = self._create("line")
        self.coordinates[item_id] = tuple(coordinates)
        return item_id

    def coords(self, item_id: int, *coordinates) -> None:
        self.coordinates[item_id] = tuple(coordinates)

    def itemconfig(self, _item_id: int, **_options) -> None:
        return

    def delete(self, item_id: int) -> None:
        self.deleted.append(item_id)


def test_selected_spot_gizmo_reuses_a_small_retained_canvas_item_set() -> None:
    scene = Scene("light gizmo")
    entity = scene.create_entity("spot", entity_id="spot")
    transform = TransformComponent(x=2.0, y=1.0, rotation=45.0)
    entity.add_component(transform)
    entity.add_component(
        component_from_dict(
            {
                "type": "light_2d",
                "kind": "spot",
                "radius": 3.0,
                "cone_angle": 50.0,
            }
        )
    )
    canvas = RecordingCanvas()
    camera = ViewportCamera((400, 300))
    colors = {"accent": "#4f91ad", "accent_ink": "#ffffff"}

    gizmo = update_light_gizmo(canvas, scene, "spot", camera, colors, None)

    assert gizmo is not None
    assert len(gizmo.items) == 4
    assert [kind for kind, _item_id in canvas.created] == ["oval", "oval", "line", "line"]
    created = tuple(canvas.created)
    old_range = canvas.coordinates[gizmo.items[0]]
    old_direction = canvas.coordinates[gizmo.items[2]]

    transform.rotation = 90.0
    updated = update_light_gizmo(canvas, scene, "spot", camera, colors, gizmo)

    assert updated is gizmo
    assert tuple(canvas.created) == created
    assert canvas.coordinates[gizmo.items[0]] == old_range
    assert canvas.coordinates[gizmo.items[2]] != old_direction
    assert len(canvas.coordinates[gizmo.items[2]]) == 4

    assert update_light_gizmo(canvas, scene, None, camera, colors, gizmo) is None
    assert canvas.deleted == list(gizmo.items)
