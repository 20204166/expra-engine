"""Regression checks for the local wheel installer boundary."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
INSTALL_USER = ROOT / "scripts" / "install-user.sh"
INSTALL_ONLINE = ROOT / "scripts" / "install-online.sh"
INSTALL_COMMON = ROOT / "scripts" / "install-common.sh"


def test_install_common_never_targets_the_checkout_venv() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert "here/.venv/bin/python" not in script
    assert "sys.prefix != sys.base_prefix" in script
    assert "--break-system-packages" in script
    assert "env -u PYTHONPATH" in script


def test_install_common_supports_explicit_system_mode() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert "--system" in script
    assert "sudo -H" in script


def test_install_common_user_mode_uses_version_specific_venv() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert "versions" in script
    assert "current" in script
    assert "-m venv" in script
    assert "$HOME/.local/share/expra-engine" in script


def test_install_common_verifies_installed_version() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert "importlib.metadata" in script
    assert "expected_version" in script
    assert "installed_version" in script


def test_install_common_manages_user_launcher_atomically() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert "$HOME/.local/bin" in script
    assert "expra-editor" in script
    assert "mktemp" in script
    assert "mv -f" in script
    assert "not overwriting" in script


def test_install_user_delegates_to_the_shared_installer() -> None:
    script = INSTALL_USER.read_text(encoding="utf-8")

    assert "install-common.sh" in script
    assert "install_wheel" in script
    assert 'PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m expra_engine._release verify-wheel' in script


def test_install_user_version_check_does_not_use_checkout_metadata() -> None:
    script = INSTALL_USER.read_text(encoding="utf-8")

    assert 'export PYTHONPATH="$here/src' not in script


def test_install_online_verifies_checksum_before_installing() -> None:
    script = INSTALL_ONLINE.read_text(encoding="utf-8")

    assert "sha256sum" in script
    assert "install-common.sh" in script
    assert "install_wheel" in script
