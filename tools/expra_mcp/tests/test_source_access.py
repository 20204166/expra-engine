"""Unit tests for the path-containment boundary that every source tool and
resource relies on -- these must hold before any protocol-level test matters.
"""

from __future__ import annotations

import conftest
import pytest
from expra_dev_mcp.config import ExecutionConfig, ExpraMcpConfig, ReferenceConfig, WorkspaceConfig
from expra_dev_mcp.source_access import SourceAccessError, get_root, resolve_relative_path

REPO_ROOT = conftest.REPO_ROOT


def _cfg() -> ExpraMcpConfig:
    return ExpraMcpConfig(
        workspace=WorkspaceConfig(expra_root=REPO_ROOT),
        references={"godot": ReferenceConfig(path=REPO_ROOT.parent / "godot-master")},
        execution=ExecutionConfig(),
        config_path=REPO_ROOT / ".expra-mcp.test.toml",
    )


def test_unknown_repo_id_rejected() -> None:
    with pytest.raises(SourceAccessError):
        get_root(_cfg(), "not-a-real-repo")


def test_reference_root_is_always_read_only_even_if_config_says_otherwise() -> None:
    cfg = ExpraMcpConfig(
        workspace=WorkspaceConfig(expra_root=REPO_ROOT),
        references={"godot": ReferenceConfig(path=REPO_ROOT.parent / "godot-master", read_only=False)},
        config_path=REPO_ROOT / ".expra-mcp.test.toml",
    )
    root = get_root(cfg, "godot")
    assert root.read_only is True


def test_parent_traversal_is_rejected() -> None:
    root = get_root(_cfg(), "expra")
    with pytest.raises(SourceAccessError):
        resolve_relative_path(root, "../../../../etc/passwd")


def test_absolute_path_is_rejected() -> None:
    root = get_root(_cfg(), "expra")
    with pytest.raises(SourceAccessError):
        resolve_relative_path(root, "/etc/passwd")


def test_nul_byte_is_rejected() -> None:
    root = get_root(_cfg(), "expra")
    with pytest.raises(SourceAccessError):
        resolve_relative_path(root, "pyproject.toml\x00.py")


def test_normal_relative_path_resolves_inside_root() -> None:
    root = get_root(_cfg(), "expra")
    resolved = resolve_relative_path(root, "pyproject.toml")
    assert resolved == (REPO_ROOT / "pyproject.toml").resolve()


def test_dotdot_that_stays_inside_root_is_allowed() -> None:
    root = get_root(_cfg(), "expra")
    resolved = resolve_relative_path(root, "src/../pyproject.toml")
    assert resolved == (REPO_ROOT / "pyproject.toml").resolve()
