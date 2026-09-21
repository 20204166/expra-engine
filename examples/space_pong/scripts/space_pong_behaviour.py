"""Project-owned Space Pong rules built on Expra's generic runtime services."""

from __future__ import annotations

from typing import Any, cast

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import EngineRunState
from expra_engine.runtime.behaviour import Behaviour, exposed
from expra_engine.runtime.physics_world import PhysicsWorld2D
from expra_engine.runtime.timeline import Timeline
from expra_engine.runtime.tween import Tween
from expra_engine.runtime.ui import GameCanvas, Insets, Label, LayoutSpec, Viewport


class SpacePongBehaviour(Behaviour):
    """Own the sample's rules while scene data remains generic and editable."""

    paddle_speed = exposed(32.0, min=0.0, category="Movement")
    ball_speed = exposed(18.0, min=0.0, category="Movement")
    winning_score = exposed(3, min=1, category="Match")
    ai_difficulty = exposed(0.65, min=0.0, max=1.0, category="Match")

    def __init__(self) -> None:
        super().__init__()
        self.score = (0, 0)
        self.status = "playing"
        self.winner = ""
        self.hit_feedback = 0.0
        self.ball_velocity = (34.0, 12.0)
        self.timeline = Timeline()
        self.feedback = Tween(1.0, 0.0, 0.18)
        self.physics: PhysicsWorld2D | None = None
        self.ui = GameCanvas(reference_resolution=(800, 600))
        self._score_labels: dict[str, Label] = {}

    def on_start(self) -> None:
        self.score = (0, 0)
        self.status = "playing"
        self.winner = ""
        self.hit_feedback = 0.0
        self.ball_velocity = (float(self.ball_speed), 12.0)
        self.physics = PhysicsWorld2D(cast(Any, self.scene))
        self._build_ui()
        self._update_hud()

    def on_stop(self) -> None:
        self.timeline.stop()
        self.physics = None

    def on_fixed_update(self, dt: float) -> None:
        self.timeline.advance(dt)
        self.hit_feedback = self.feedback.step(dt)
        if self.status != "playing" or self.scene is None:
            return

        self._move_paddles(dt)
        ball = self._transform("ball")
        velocity_x, velocity_y = self.ball_velocity
        ball.x += velocity_x * dt
        ball.y += velocity_y * dt
        if abs(ball.y) >= 28.0:
            ball.y = max(-28.0, min(28.0, ball.y))
            self.ball_velocity = (velocity_x, -velocity_y)

        if self.physics is not None:
            overlaps = self.physics.overlap(self._entity("ball").entity_id, include_triggers=False)
            if overlaps:
                self.ball_velocity = (-velocity_x, velocity_y)
                self._start_feedback()
        if ball.x <= -50.0:
            self.score_point("right")
        elif ball.x >= 50.0:
            self.score_point("left")

    def on_input(self, event: object, signal: object = None) -> bool:
        del signal
        if getattr(getattr(event, "action", None), "value", None) != "pause":
            if getattr(getattr(event, "action", None), "value", None) == "restart" and getattr(event, "phase", None) == "pressed":
                return self.restart()
            return False
        if getattr(event, "phase", None) != "pressed":
            return False
        return self.toggle_pause()

    def score_point(self, side: str) -> None:
        left, right = self.score
        self.score = (left + (side == "left"), right + (side == "right"))
        self._start_feedback()
        if max(self.score) >= int(self.winning_score):
            self.status = "won"
            self.winner = side
        self._update_hud()

    def toggle_pause(self) -> bool:
        engine = cast(Any, self.engine)
        if engine is None:
            return False
        if engine.run_state is EngineRunState.PLAY:
            return engine.pause()
        if engine.run_state is EngineRunState.PAUSED:
            return engine.play()
        return False

    def restart(self) -> bool:
        engine = cast(Any, self.engine)
        if engine is None or engine.run_state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            return False
        engine.stop()
        engine.play()
        return True

    def resize(self, size: tuple[int, int]) -> dict[str, Any]:
        result = self.ui.layout(Viewport(*size), Insets())
        return {name: result.rect(name) for name in self._score_labels}

    def _move_paddles(self, dt: float) -> None:
        for tag, positive, negative in (
            ("left_paddle", "left_up", "left_down"),
            ("right_paddle", "right_up", "right_down"),
        ):
            transform = self._transform(tag)
            direction = int(self.input.is_held(positive)) - int(self.input.is_held(negative))
            transform.y = max(-22.0, min(22.0, transform.y + direction * float(self.paddle_speed) * dt))

    def _start_feedback(self) -> None:
        self.feedback.reset()
        self.hit_feedback = 1.0
        self.timeline.schedule(
            duration=0.18,
            on_update=lambda progress: setattr(self, "hit_feedback", 1.0 - progress),
        )

    def _build_ui(self) -> None:
        self.ui = GameCanvas(reference_resolution=(800, 600))
        for name, anchor in (("score_left", 0.25), ("score_right", 0.75)):
            label = Label(
                name,
                text="0",
                layout=LayoutSpec(
                    anchor_min=(anchor, 1.0),
                    anchor_max=(anchor, 1.0),
                    pivot=(0.5, 1.0),
                    preferred_size=(120.0, 56.0),
                ),
            )
            self.ui.add(label)
            self._score_labels[name] = label

    def _update_hud(self) -> None:
        left, right = self.score
        if self._score_labels:
            self._score_labels["score_left"].text = str(left)
            self._score_labels["score_right"].text = str(right)
        self._set_text("score_left", str(left))
        self._set_text("score_right", str(right))
        self._set_text("status", "WIN: " + self.winner if self.status == "won" else self.status.upper())

    def _set_text(self, tag: str, value: str) -> None:
        entity = self._entity(tag)
        component = entity.get_component(__import__(
            "expra_engine.runtime.visual_components", fromlist=["TextComponent"]
        ).TextComponent)
        if component is not None:
            component.text = value

    def _entity(self, tag: str) -> Any:
        scene = cast(Any, self.scene)
        matches = scene.get_entities_by_tag(tag)
        if not matches:
            raise LookupError(f"missing tagged entity: {tag}")
        return matches[0]

    def _transform(self, tag: str) -> TransformComponent:
        transform = self._entity(tag).get_component(TransformComponent)
        if transform is None:
            raise LookupError(f"tagged entity has no transform: {tag}")
        return transform
