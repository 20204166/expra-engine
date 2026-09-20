from pathlib import Path

import pytest

from expra_engine.filesystem import (
    DuplicateResourceError,
    ResourceId,
    ResourceNotFoundError,
    ResourcePermissionError,
)
from expra_engine.filesystem.mounts import ArchiveMount, DirectoryMount, MountSpec
from expra_engine.filesystem.resources import ResourceResolver


def _mount(root: Path, name: str, *, precedence: int = 0, read_only: bool = True) -> DirectoryMount:
    return DirectoryMount(
        root,
        MountSpec(
            name=name,
            scheme="assets",
            precedence=precedence,
            read_only=read_only,
        ),
    )


def test_directory_mount_reads_confined_resource_and_reports_metadata(tmp_path: Path) -> None:
    (tmp_path / "textures").mkdir()
    resource_path = tmp_path / "textures" / "player.png"
    resource_path.write_bytes(b"pixels")
    resolver = ResourceResolver([_mount(tmp_path, "project")])

    handle = resolver.resolve(ResourceId.parse("assets://textures/player.png"))

    assert handle.read_bytes() == b"pixels"
    assert handle.metadata.size == 6
    assert handle.metadata.physical_path == resource_path.resolve()
    assert handle.mount == "project"
    assert handle.logical_id == ResourceId.parse("assets://textures/player.png")


def test_missing_resource_is_typed(tmp_path: Path) -> None:
    resolver = ResourceResolver([_mount(tmp_path, "project")])

    with pytest.raises(ResourceNotFoundError):
        resolver.resolve(ResourceId.parse("assets://missing.txt"))


def test_directory_mount_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    root = tmp_path / "assets"
    root.mkdir()
    (root / "link.txt").symlink_to(outside / "secret.txt")

    resolver = ResourceResolver([_mount(root, "project")])

    with pytest.raises(ResourceNotFoundError):
        resolver.resolve(ResourceId.parse("assets://link.txt"))


def test_read_only_mount_rejects_writes(tmp_path: Path) -> None:
    resolver = ResourceResolver([_mount(tmp_path, "package")])

    with pytest.raises(ResourcePermissionError):
        resolver.write(ResourceId.parse("assets://new.txt"), b"data")


def test_higher_precedence_mount_wins(tmp_path: Path) -> None:
    low = tmp_path / "low"
    high = tmp_path / "high"
    low.mkdir()
    high.mkdir()
    (low / "same.txt").write_text("low")
    (high / "same.txt").write_text("high")
    resolver = ResourceResolver([_mount(low, "low"), _mount(high, "high", precedence=10)])

    handle = resolver.resolve(ResourceId.parse("assets://same.txt"))

    assert handle.read_bytes() == b"high"
    assert handle.mount == "high"


def test_equal_precedence_duplicate_is_an_error(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "same.txt").write_text("first")
    (second / "same.txt").write_text("second")
    resolver = ResourceResolver([_mount(first, "first"), _mount(second, "second")])

    with pytest.raises(DuplicateResourceError):
        resolver.resolve(ResourceId.parse("assets://same.txt"))


def test_unmount_removes_resources_and_physical_provenance_is_not_logical_identity(
    tmp_path: Path,
) -> None:
    (tmp_path / "file.txt").write_text("content")
    resolver = ResourceResolver([_mount(tmp_path, "project")])
    resource_id = ResourceId.parse("assets://file.txt")

    handle = resolver.resolve(resource_id)
    resolver.unmount("project")

    assert handle.metadata.physical_path == (tmp_path / "file.txt").resolve()
    assert str(handle.logical_id) == "assets://file.txt"
    with pytest.raises(ResourceNotFoundError):
        resolver.resolve(resource_id)


def test_writable_directory_mount_writes_confined_file(tmp_path: Path) -> None:
    resolver = ResourceResolver([_mount(tmp_path, "project", read_only=False)])
    resource_id = ResourceId.parse("assets://new/file.txt")

    resolver.write(resource_id, b"hello")

    assert (tmp_path / "new" / "file.txt").read_bytes() == b"hello"
    assert resolver.resolve(resource_id).read_bytes() == b"hello"


def test_archive_mount_has_the_same_handle_contract_as_a_directory(
    tmp_path: Path,
) -> None:
    import zipfile

    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("textures/player.png", b"pixels")
    mount = ArchiveMount(
        archive,
        MountSpec(name="archive", scheme="assets", read_only=True),
    )

    handle = ResourceResolver([mount]).resolve(ResourceId.parse("assets://textures/player.png"))

    assert handle.read_bytes() == b"pixels"
    assert handle.metadata.size == 6
    assert handle.metadata.physical_path is None
    assert handle.metadata.modified_ns is not None
    assert mount.read_bytes(ResourceId.parse("assets://textures/player.png")) == b"pixels"


def test_archive_mount_is_read_only(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("file.txt", b"data")
    resolver = ResourceResolver([ArchiveMount(archive, MountSpec(name="archive", scheme="assets"))])

    with pytest.raises(ResourcePermissionError):
        resolver.write(ResourceId.parse("assets://file.txt"), b"new")


def test_archive_mount_participates_in_precedence(tmp_path: Path) -> None:
    import zipfile

    directory = tmp_path / "directory"
    directory.mkdir()
    (directory / "same.txt").write_bytes(b"directory")
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("same.txt", b"archive")
    resolver = ResourceResolver(
        [
            _mount(directory, "directory", precedence=10),
            ArchiveMount(archive, MountSpec(name="archive", scheme="assets", precedence=20)),
        ]
    )

    assert resolver.resolve(ResourceId.parse("assets://same.txt")).read_bytes() == b"archive"
