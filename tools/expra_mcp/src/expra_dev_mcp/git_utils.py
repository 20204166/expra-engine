"""Shared read-only git subprocess helpers, used by both workspace_doctor's
identity checks and repo_inspect's git introspection. Never anything beyond
read-only git subcommands here -- no commit/push/checkout/reset/clean.
"""

from __future__ import annotations

from pathlib import Path

from . import command_runner
from .command_runner import CommandResult


async def run_git(repo: Path, args: list[str], *, timeout_seconds: float = 20.0) -> CommandResult:
    return await command_runner.run_command(
        ["git", "-C", str(repo), *args], timeout_seconds=timeout_seconds, max_output_bytes=512 * 1024
    )


async def git_identity(repo: Path) -> tuple[str | None, bool | None]:
    """Return ``(head_commit, dirty)`` for ``repo``, or ``(None, None)`` if
    it is not a git checkout at all (true for every current reference repo
    on this machine -- callers must degrade gracefully, not error).
    """

    if not (repo / ".git").exists():
        return None, None
    commit_result = await run_git(repo, ["rev-parse", "HEAD"], timeout_seconds=10)
    status_result = await run_git(repo, ["status", "--porcelain"], timeout_seconds=10)
    commit = commit_result.stdout.strip() if commit_result.ok else None
    dirty = bool(status_result.stdout.strip()) if status_result.ok else None
    return commit, dirty
