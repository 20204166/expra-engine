"""Regression checks for the local wheel installer boundary."""

from pathlib import Path

INSTALL_USER = Path(__file__).parents[1] / "scripts" / "install-user.sh"


def test_install_user_does_not_use_checkout_metadata_for_installed_version_check() -> None:
    script = INSTALL_USER.read_text(encoding="utf-8")

    assert 'export PYTHONPATH="$here/src' not in script
    assert 'PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m' in script
    assert 'env -u PYTHONPATH "$py" "$@"' in script
    assert 'installed_version="$(run_target_python -c' in script
