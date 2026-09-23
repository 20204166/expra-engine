from __future__ import annotations

import sys
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

REPO_ROOT = TOOL_ROOT.parents[1]
DOWNLOADS_ROOT = REPO_ROOT.parent

REFERENCE_PATHS = {
    "godot": DOWNLOADS_ROOT / "godot-master",
    "ppb": DOWNLOADS_ROOT / "pursuedpybear-canon",
    "minipy": DOWNLOADS_ROOT / "MiniPyEngine-main",
    "ursina": DOWNLOADS_ROOT / "ursina-master",
    "exp_ui": DOWNLOADS_ROOT / "exp",
}


def full_config():
    from expra_dev_mcp.config import (
        ExecutionConfig,
        ExpraMcpConfig,
        ReferenceConfig,
        WorkspaceConfig,
    )

    references = {
        ref_id: ReferenceConfig(path=path) for ref_id, path in REFERENCE_PATHS.items() if path.is_dir()
    }
    return ExpraMcpConfig(
        workspace=WorkspaceConfig(expra_root=REPO_ROOT, default_project="examples/blacksite_relay"),
        references=references,
        execution=ExecutionConfig(),
        config_path=REPO_ROOT / ".expra-mcp.test.toml",
    )
