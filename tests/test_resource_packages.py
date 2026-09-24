import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from expra_engine.filesystem import (
    MalformedPackageManifestError,
    ResourceId,
    UnsafeArchiveMemberError,
)
from expra_engine.filesystem.mounts import ArchiveMount, MountSpec
from expra_engine.filesystem.packages import PackageManifest


def _write_package(path: Path, *, manifest: object, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("package.json", json.dumps(manifest))
        for name, data in members.items():
            archive.writestr(name, data)


def _manifest(data: bytes, *, resource_path: str = "data/file.txt") -> dict[str, object]:
    return {
        "identity": "demo",
        "version": "1.2.0",
        "format_version": 1,
        "resources": [
            {
                "path": resource_path,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "dependencies": [],
            }
        ],
        "dependencies": ["engine://fonts/default.ttf"],
    }


def test_manifest_validates_identity_resources_and_dependencies() -> None:
    manifest = PackageManifest.from_mapping(_manifest(b"hello"))

    assert manifest.identity == "demo"
    assert manifest.version == "1.2.0"
    assert manifest.format_version == 1
    assert manifest.resources[0].size == 5
    assert manifest.dependencies == ("engine://fonts/default.ttf",)


@pytest.mark.parametrize(
    "manifest",
    [
        {},
        {"identity": "demo", "version": "1", "format_version": 1, "resources": []},
        {**_manifest(b"hello"), "version": ""},
        {**_manifest(b"hello"), "resources": [{"path": "data/file.txt", "size": 4}]},
    ],
)
def test_malformed_manifests_are_rejected(manifest: object) -> None:
    with pytest.raises(MalformedPackageManifestError):
        PackageManifest.from_mapping(manifest)


def test_archive_rejects_unsafe_members_and_duplicate_logical_names(tmp_path: Path) -> None:
    unsafe_names = [
        "../secret.txt",
        "/absolute.txt",
        "dir/../../secret.txt",
        "dir\\file.txt",
        "C:/windows/system.ini",
    ]
    for index, name in enumerate(unsafe_names):
        archive = tmp_path / f"unsafe-{index}.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(name, b"bad")
        with pytest.raises(UnsafeArchiveMemberError):
            ArchiveMount(
                archive, MountSpec(name=f"unsafe-{index}", scheme="package", namespace="demo")
            )

    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("file.txt", b"one")
        zf.writestr("file.txt", b"two")
    with pytest.raises(UnsafeArchiveMemberError):
        ArchiveMount(archive, MountSpec(name="duplicate", scheme="assets"))


def test_archive_validates_manifest_agreement_and_extracts_atomically(tmp_path: Path) -> None:
    data = b"hello"
    archive = tmp_path / "demo.zip"
    _write_package(archive, manifest=_manifest(data), members={"data/file.txt": data})
    mount = ArchiveMount(
        archive,
        MountSpec(name="demo", scheme="package", namespace="demo"),
    )
    resource_id = ResourceId.parse("package://demo/data/file.txt")

    extracted = mount.extract(resource_id, tmp_path / "cache")

    assert extracted.read_bytes() == data
    assert hashlib.sha256(data).hexdigest() in str(extracted)
    assert mount.extract(resource_id, tmp_path / "cache") == extracted


def test_archive_rejects_manifest_resource_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    _write_package(archive, manifest=_manifest(b"wrong"), members={"data/file.txt": b"actual"})

    with pytest.raises(MalformedPackageManifestError):
        ArchiveMount(archive, MountSpec(name="bad", scheme="package", namespace="demo"))


def test_package_scheme_archive_without_manifest_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("data/file.txt", b"data")

    with pytest.raises(MalformedPackageManifestError):
        ArchiveMount(archive, MountSpec(name="no-manifest", scheme="package", namespace="demo"))
