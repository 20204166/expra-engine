from pathlib import Path

import pytest

from expra_engine.filesystem import (
    InvalidResourceIdError,
    ResourceId,
    ResourceNotFoundError,
)


def test_parses_and_stably_formats_resource_ids() -> None:
    resource_id = ResourceId.parse("assets://textures/player.png")

    assert resource_id.scheme == "assets"
    assert resource_id.namespace is None
    assert resource_id.path == "textures/player.png"
    assert str(resource_id) == "assets://textures/player.png"


def test_parses_package_namespace() -> None:
    resource_id = ResourceId.parse("package://starter-kit/textures/player.png")

    assert resource_id.scheme == "package"
    assert resource_id.namespace == "starter-kit"
    assert resource_id.path == "textures/player.png"
    assert str(resource_id) == "package://starter-kit/textures/player.png"


def test_normalizes_project_path_separators() -> None:
    resource_id = ResourceId.from_project_path(Path("textures\\player.png"))

    assert resource_id == ResourceId.parse("assets://textures/player.png")


@pytest.mark.parametrize(
    "value",
    [
        "Assets://textures/player.png",
        "assets:///textures/player.png",
        "assets://textures//player.png",
        "assets://textures/./player.png",
        "assets://textures/../player.png",
        "assets:///absolute.png",
        "assets://C:/absolute.png",
        "assets://textures/player\x00.png",
        "assets://textures\\player.png",
        "assets://textures/player.png/",
        "assets://textures//",
        "assets://",
    ],
)
def test_rejects_invalid_resource_ids(value: str) -> None:
    with pytest.raises(InvalidResourceIdError):
        ResourceId.parse(value)


def test_resource_id_is_immutable() -> None:
    resource_id = ResourceId.parse("engine://fonts/default.ttf")

    with pytest.raises(AttributeError):
        resource_id.path = "fonts/other.ttf"  # type: ignore[misc]


def test_typed_errors_keep_safe_context_without_absolute_paths() -> None:
    error = ResourceNotFoundError(
        operation="read",
        logical_id=ResourceId.parse("assets://textures/player.png"),
        mount="project-assets",
        package="starter-kit",
        path="/home/user/private/project/assets/textures/player.png",
    )

    assert error.operation == "read"
    assert error.logical_id == ResourceId.parse("assets://textures/player.png")
    assert error.mount == "project-assets"
    assert error.package == "starter-kit"
    assert "/home/user" not in str(error)
    assert "assets://textures/player.png" in str(error)
