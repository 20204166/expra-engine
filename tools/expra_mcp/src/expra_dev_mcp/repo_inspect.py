"""repo_inspect: read-only git introspection, Expra root only.

Never commit/push/checkout/reset/clean/rebase/merge -- this module doesn't
even have functions for those, not just a config flag disabling them.
"""

from __future__ import annotations

from pathlib import Path

from . import git_utils


class RepoInspectError(RuntimeError):
    pass


async def _require_ok(repo: Path, args: list[str]) -> str:
    result = await git_utils.run_git(repo, args)
    if not result.ok:
        raise RepoInspectError(result.launch_error or result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


async def branch(repo: Path) -> str:
    return (await _require_ok(repo, ["rev-parse", "--abbrev-ref", "HEAD"])).strip()


async def head_commit(repo: Path) -> str:
    return (await _require_ok(repo, ["rev-parse", "HEAD"])).strip()


async def status_porcelain(repo: Path) -> list[tuple[str, str]]:
    raw = await _require_ok(repo, ["status", "--porcelain=v1"])
    changes: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if not line:
            continue
        changes.append((line[:2].strip(), line[3:]))
    return changes


async def diff(repo: Path) -> str:
    return await _require_ok(repo, ["diff"])


async def diff_stat(repo: Path) -> str:
    return await _require_ok(repo, ["diff", "--stat"])


async def recent_commits(repo: Path, count: int) -> list[str]:
    raw = await _require_ok(repo, ["log", f"-n{count}", "--oneline"])
    return [line for line in raw.splitlines() if line]
