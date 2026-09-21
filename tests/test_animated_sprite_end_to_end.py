"""End-to-end regression coverage for AnimatedSprite2D integration seams."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import SetComponentPropertyCommand
from expra_engine.runtime import project_runner
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    SpriteAnimation2D,
    SpriteFrame2D,
    SpriteFrames2D,
)
from expra_engine.runtime.behaviour import Behaviour
from expra_engine.runtime.events import Update
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.ui.viewport import build_editor_render_target


def _frames(prefix: str) -> SpriteFrames2D:
    return SpriteFrames2D(
        {
            "walk": SpriteAnimation2D(
                (SpriteFrame2D(f"{prefix}-0.png"), SpriteFrame2D(f"{prefix}-1.png")),
                speed_fps=10.0,
            )
        }
    )


def _engine_with_scene(scene: Scene) -> Engine:
    engine = Engine()
    engine.set_scene(scene)
    engine.play()
    return engine


def test_multiple_components_advance_and_render_independently_end_to_end() -> None:
    scene = Scene("multiple")
    entity = scene.create_entity("hero", entity_id="hero")
    first = AnimatedSprite2DComponent(_frames("first"), autoplay="walk")
    second = AnimatedSprite2DComponent(_frames("second"), autoplay="walk")
    entity.add_component(first)
    entity.add_component(second)
    engine = _engine_with_scene(scene)

    engine.signal(Update(0.1))
    engine.tick(0.0)
    active_scene = engine.active_scene
    assert active_scene is not None
    frame = extract_render_frame(
        active_scene, animated_players=engine.animated_sprite_system.players
    )

    assert len(engine.animated_sprite_system.players) == 2
    assert [item.material.texture_id for item in frame.items] == ["first-1.png", "second-1.png"]


def test_sprite_events_use_the_canonical_targeted_event_queue_end_to_end() -> None:
    class EventReceiver(Behaviour):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[str] = []

        def on_sprite_event(self, event: Any) -> None:
            self.events.append(event.kind)

    scene = Scene("events")
    entity = scene.create_entity("hero", entity_id="hero")
    entity.add_component(AnimatedSprite2DComponent(_frames("hero"), autoplay="walk"))
    engine = _engine_with_scene(scene)
    active_scene = engine.active_scene
    assert active_scene is not None
    runtime_entity = active_scene.find_entity("hero")
    assert runtime_entity is not None
    receiver = EventReceiver()
    runtime_entity.add_behaviour(receiver, runtime_factory=EventReceiver)

    engine.signal(Update(0.3))
    engine.tick(0.0)

    assert receiver.events == [
        "frame_changed",
        "animation_looped",
        "frame_changed",
        "frame_changed",
    ]


def test_editor_target_uses_live_player_state_and_offset_aware_culling_end_to_end() -> None:
    scene = Scene("editor")
    entity = scene.create_entity("hero", entity_id="hero")
    entity.add_component(
        __import__(
            "expra_engine.core.component", fromlist=["TransformComponent"]
        ).TransformComponent(x=20.0)
    )
    component = AnimatedSprite2DComponent(_frames("hero"), autoplay="walk", offset=(-20.0, 0.0))
    entity.add_component(component)
    engine = _engine_with_scene(scene)
    engine.signal(Update(0.1))
    engine.tick(0.0)

    target = build_editor_render_target(
        engine.active_scene,
        viewport=(200, 100),
        animated_players=engine.animated_sprite_system.players,
    )

    assert [item.material.texture_id for item in target.items] == ["hero-1.png"]


def test_project_runner_loads_project_resources_and_live_animated_frames_end_to_end(
    monkeypatch: Any, tmp_path: Path
) -> None:
    project = Project.create("Animated", tmp_path / "animated")
    (project.assets_dir / "hero-0.png").write_bytes(b"first")
    (project.assets_dir / "hero-1.png").write_bytes(b"second")
    scene = Scene("main")
    entity = scene.create_entity("hero")
    entity.add_component(AnimatedSprite2DComponent(_frames("hero"), autoplay="walk"))
    project.save_scene(scene)

    captured: dict[str, Any] = {}

    class Renderer:
        def __init__(self, _pygame: Any, _surface: Any, **kwargs: Any) -> None:
            captured["provider"] = kwargs.get("resource_provider")

    class Runtime:
        def __init__(self, engine: Engine, _renderer: Any, **kwargs: Any) -> None:
            self.engine = engine
            self.frame_factory = kwargs["frame_factory"]

        def run(self) -> None:
            self.engine.tick(0.1)
            captured["frame"] = self.frame_factory(self.engine, 0.1)

    pygame = SimpleNamespace(image=SimpleNamespace(load=lambda stream: stream.read()))
    monkeypatch.setitem(sys.modules, "pygame", pygame)
    monkeypatch.setattr(project_runner, "PygameRenderer", Renderer)
    monkeypatch.setattr(project_runner, "PygameRuntime", Runtime)

    project_runner.run_project(project.path)

    assert captured["provider"] is not None
    assert captured["provider"]("assets://hero-1.png") == b"second"
    assert [item.material.texture_id for item in captured["frame"].items] == ["hero-1.png"]


def test_inspector_edits_round_trip_frame_json_without_corrupting_configuration_end_to_end() -> (
    None
):
    scene = Scene("inspector")
    entity = scene.create_entity("hero")
    component = AnimatedSprite2DComponent(_frames("old"), animation="walk", offset=(2.0, 3.0))
    entity.add_component(component)
    spec = component_type_spec("animated_sprite")
    frames = next(field for field in spec.fields if field.name == "frames")
    offset = next(field for field in spec.fields if field.name == "offset")

    updated_frames = _frames("new").to_dict()
    converted_frames = frames.convert(json.dumps(updated_frames), original=component.frames)
    SetComponentPropertyCommand(
        scene, entity.entity_id, AnimatedSprite2DComponent, "frames", converted_frames
    ).execute()
    converted_offset = offset.convert("2.0", original=component.offset)
    SetComponentPropertyCommand(
        scene, entity.entity_id, AnimatedSprite2DComponent, "offset", converted_offset
    ).execute()

    assert component.frames.to_dict() == updated_frames
    assert component.offset == (2.0, 3.0)
    assert Scene.from_dict(scene.to_dict()).to_dict() == scene.to_dict()
