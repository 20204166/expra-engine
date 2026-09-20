"""Core game engine model: Engine, Project, Scene, Entity, Component."""

from expra_engine.core.bounds import Bounds2D
from expra_engine.core.component import Component, TransformComponent
from expra_engine.core.directions import (
    ALL,
    DOWN,
    DOWN_LEFT,
    DOWN_RIGHT,
    LEFT,
    RIGHT,
    UP,
    UP_LEFT,
    UP_RIGHT,
)
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.entity import Entity
from expra_engine.core.math_utils import (
    clamp,
    inverselerp,
    lerp,
    lerp_angle,
    lerp_exponential_decay,
    round_to_closest,
)
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.core.string_utils import (
    camel_to_snake,
    multireplace,
    snake_to_camel,
    snake_to_lower_camel,
)

__all__ = [
    "ALL",
    "DOWN",
    "DOWN_LEFT",
    "DOWN_RIGHT",
    "LEFT",
    "RIGHT",
    "UP",
    "UP_LEFT",
    "UP_RIGHT",
    "Bounds2D",
    "Component",
    "Engine",
    "EngineRunState",
    "Entity",
    "Project",
    "Scene",
    "TransformComponent",
    "camel_to_snake",
    "clamp",
    "inverselerp",
    "lerp",
    "lerp_angle",
    "lerp_exponential_decay",
    "multireplace",
    "round_to_closest",
    "snake_to_camel",
    "snake_to_lower_camel",
]
