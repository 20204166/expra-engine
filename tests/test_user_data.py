from pathlib import Path

import pytest

from expra_engine.filesystem.user_data import UserDataError, UserDataStore


def test_application_and_game_data_use_separate_namespaced_roots(tmp_path: Path) -> None:
    store = UserDataStore(
        tmp_path / "private",
        application_namespace="expra",
        game_namespace="game-one",
    )

    store.write_text("settings.json", "application", namespace="application")
    store.write_text("settings.json", "game", namespace="game")

    assert store.read_text("settings.json", namespace="application") == "application"
    assert store.read_text("settings.json", namespace="game") == "game"
    assert (tmp_path / "private" / "expra" / "settings.json").exists()
    assert (tmp_path / "private" / "game-one" / "settings.json").exists()


@pytest.mark.parametrize(
    "path", ["../escape.txt", "/absolute.txt", "C:/absolute.txt", "a/../b.txt", "a\\b.txt", ""]
)
def test_rejects_unsafe_relative_paths(tmp_path: Path, path: str) -> None:
    store = UserDataStore(tmp_path / "private")

    with pytest.raises(UserDataError):
        store.write_text(path, "secret")


def test_rejects_symlink_escape_for_reads_and_writes(tmp_path: Path) -> None:
    root = tmp_path / "private"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    store = UserDataStore(root)
    store.write_text("safe.txt", "safe")
    (root / "application" / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UserDataError):
        store.read_text("escape/secret.txt")
    with pytest.raises(UserDataError):
        store.write_text("escape/new.txt", "not secret")


def test_writes_are_atomic_replacements_and_support_bytes(tmp_path: Path) -> None:
    store = UserDataStore(tmp_path / "private")

    store.write_text("nested/state.txt", "old")
    store.write_text("nested/state.txt", "new")
    store.write_bytes("nested/blob.bin", b"\x00\x01")

    assert store.read_text("nested/state.txt") == "new"
    assert store.read_bytes("nested/blob.bin") == b"\x00\x01"
    assert list((tmp_path / "private" / "application" / "nested").glob("*.tmp")) == []


def test_reads_and_deletes_are_confined(tmp_path: Path) -> None:
    store = UserDataStore(tmp_path / "private")
    store.write_text("remove.txt", "value")

    assert store.delete("remove.txt") is True
    assert store.delete("remove.txt") is False
    with pytest.raises(FileNotFoundError):
        store.read_text("remove.txt")


def test_diagnostics_do_not_expose_absolute_user_paths(tmp_path: Path) -> None:
    store = UserDataStore(tmp_path / "private")

    with pytest.raises(UserDataError) as caught:
        store.read_text(str(tmp_path / "private-secret.txt"))

    assert str(tmp_path) not in str(caught.value)
    assert "<absolute-path>" in str(caught.value)


def test_user_data_is_not_a_resource_mount_or_resource_fallback(tmp_path: Path) -> None:
    store = UserDataStore(tmp_path / "private")

    assert not hasattr(store, "locate")
    assert not hasattr(store, "spec")
