"""Example: create and serialize a basic scene without launching the editor."""

import json

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene


def main() -> None:
    scene = Scene("Example Level")
    camera = scene.create_entity("Camera")
    camera.add_component(TransformComponent(x=0.0, y=0.0))

    player = scene.create_entity("Player")
    player.add_component(TransformComponent(x=100.0, y=50.0, rotation=0.0))

    enemy = scene.create_entity("Enemy")
    enemy.add_component(TransformComponent(x=-80.0, y=30.0))

    print("Scene:", scene)
    print("Entities:", [e.name for e in scene.entities])

    data = json.dumps(scene.to_dict(), indent=2)
    print("\nSerialized:")
    print(data)

    reloaded = Scene.from_dict(json.loads(data))
    print("\nReloaded:", reloaded)
    print("IDs match:", all(scene.find_entity(e.entity_id) is not None for e in reloaded.entities))


if __name__ == "__main__":
    main()
