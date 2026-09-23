"""run_checks: named development-check profiles, subprocess-only, never an
arbitrary shell. Every profile maps to a fixed, real command against the
configured Expra interpreter (or git, for diff_check) -- there is no
generic "run this string" path anywhere in this module.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import command_runner, git_utils, paths

PROFILE_TEST_GLOBS: dict[str, list[str]] = {
    "renderer": [
        "test_pygame_renderer.py",
        "test_render_extractor.py",
        "test_render_pipeline.py",
        "test_runtime_rendering.py",
    ],
    "blacksite": ["test_blacksite_relay.py"],
    "space_pong": ["test_space_pong.py"],
    "neon_arena": ["test_neon_arena.py"],
    "physics": ["test_physics_world.py", "test_runtime_physics.py"],
    "resources": [
        "test_resource_ids.py",
        "test_resource_mounts.py",
        "test_resource_packages.py",
        "test_resource_service.py",
    ],
    "backbuffer": ["test_screen_texture*.py", "test_texture_diagnostics.py"],
    "editor_texture": ["test_editor_texture_rendering.py", "test_editor_render_targets.py"],
    "export": [
        "test_export.py",
        "test_export_cli.py",
        "test_export_exporter.py",
        "test_export_manifest.py",
        "test_export_packager.py",
        "test_export_plan.py",
        "test_export_verify.py",
        "test_export_bytecode.py",
        "test_export_events.py",
        "test_export_dialog.py",
    ],
}

PYTEST_PROFILES = frozenset(
    {"renderer", "blacksite", "space_pong", "neon_arena", "physics", "resources",
     "backbuffer", "editor_texture", "export", "full", "full_xvfb", "focused"}
)
KNOWN_PROFILES = PYTEST_PROFILES | {"ruff", "pyright", "mypy", "compileall", "diff_check", "build_wheel"}


class RunChecksError(RuntimeError):
    pass


def _resolve_test_paths(expra_root: Path, profile: str) -> list[str]:
    tests_dir = expra_root / "tests"
    if profile == "full":
        return ["tests"]
    resolved: list[str] = []
    for pattern in PROFILE_TEST_GLOBS.get(profile, []):
        if "*" in pattern:
            resolved.extend(sorted(p.relative_to(expra_root).as_posix() for p in tests_dir.glob(pattern)))
        else:
            candidate = tests_dir / pattern
            if candidate.is_file():
                resolved.append(candidate.relative_to(expra_root).as_posix())
    return resolved


def _parse_junit(xml_path: Path) -> dict[str, Any]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return {}
    tests = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    failure_summaries = []
    for testcase in suite.iter("testcase"):
        for tag in ("failure", "error"):
            node = testcase.find(tag)
            if node is not None:
                classname = testcase.get("classname", "")
                name = testcase.get("name", "")
                message = (node.get("message") or "").strip()
                failure_summaries.append(f"{classname}::{name}: {message}"[:300])
    return {
        "tests_collected": tests,
        "passed": tests - failures - errors - skipped,
        "failed": failures + errors,
        "skipped": skipped,
        "failure_summaries": failure_summaries[:50],
    }


def _write_log(log_dir: Path, name: str, argv: list[str], result: command_runner.CommandResult) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    path.write_text(f"$ {' '.join(argv)}\n\n{result.stdout}\n--- stderr ---\n{result.stderr}", encoding="utf-8")
    return path


async def run_profile(
    *,
    profile: str,
    executable: str,
    expra_root: Path,
    log_dir: Path,
    test_target: str | None = None,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    if profile not in KNOWN_PROFILES:
        raise RunChecksError(f"unknown run_checks profile: {profile!r} (known: {', '.join(sorted(KNOWN_PROFILES))})")

    start = time.monotonic()

    if profile in PYTEST_PROFILES:
        if profile == "focused":
            if not test_target:
                raise RunChecksError("profile='focused' requires test_target (e.g. 'tests/test_renderer.py::test_name')")
            target_file = (expra_root / test_target.split("::")[0]).resolve()
            if not paths.is_contained(target_file, expra_root / "tests"):
                raise RunChecksError(f"test_target must be inside {expra_root / 'tests'}: {test_target!r}")
            test_paths = [test_target]
        else:
            test_paths = _resolve_test_paths(expra_root, "full" if profile == "full_xvfb" else profile)
            if not test_paths:
                raise RunChecksError(f"no test files found on disk for profile {profile!r}")

        junit_path = log_dir / "junit.xml"
        argv = [executable, "-m", "pytest", *test_paths, f"--junitxml={junit_path}", "-q"]
        if profile == "full_xvfb":
            xvfb = shutil.which("xvfb-run")
            if xvfb is None:
                raise RunChecksError("full_xvfb requested but xvfb-run is not on PATH")
            argv = [xvfb, "-a", *argv]

        result = await command_runner.run_command(
            argv, timeout_seconds=timeout_seconds, cwd=str(expra_root), max_output_bytes=2 * 1024 * 1024
        )
        log_path = _write_log(log_dir, "output.log", argv, result)

        parsed: dict[str, Any] = {}
        if junit_path.is_file():
            try:
                parsed = _parse_junit(junit_path)
            except ET.ParseError:
                parsed = {}

        return {
            "profile": profile,
            "success": result.exit_code == 0 and not result.timed_out,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": time.monotonic() - start,
            "log_path": str(log_path),
            **parsed,
        }

    if profile == "ruff":
        argv = [executable, "-m", "ruff", "check", "--output-format", "json", "src", "tests"]
        result = await command_runner.run_command(
            argv, timeout_seconds=timeout_seconds, cwd=str(expra_root), max_output_bytes=2 * 1024 * 1024
        )
        log_path = _write_log(log_dir, "ruff.log", argv, result)
        try:
            violations = json.loads(result.stdout) if result.stdout.strip() else []
        except ValueError:
            violations = []
        summaries = [
            f"{v.get('filename')}:{v.get('location', {}).get('row')}: {v.get('code')} {v.get('message')}"
            for v in violations[:50]
        ]
        return {
            "profile": profile,
            "success": result.exit_code == 0 and not result.timed_out,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": time.monotonic() - start,
            "failed": len(violations),
            "failure_summaries": summaries,
            "log_path": str(log_path),
        }

    if profile == "pyright":
        argv = [executable, "-m", "pyright", "--outputjson"]
        result = await command_runner.run_command(
            argv, timeout_seconds=timeout_seconds, cwd=str(expra_root), max_output_bytes=4 * 1024 * 1024
        )
        log_path = _write_log(log_dir, "pyright.log", argv, result)
        try:
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except ValueError:
            payload = {}
        diagnostics = payload.get("generalDiagnostics", [])
        errors = [d for d in diagnostics if d.get("severity") == "error"]
        summaries = [
            f"{d.get('file')}:{d.get('range', {}).get('start', {}).get('line')}: {d.get('message')}"
            for d in errors[:50]
        ]
        return {
            "profile": profile,
            "success": len(errors) == 0 and not result.timed_out,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": time.monotonic() - start,
            "failed": len(errors),
            "failure_summaries": summaries,
            "log_path": str(log_path),
        }

    if profile == "mypy":
        argv = [executable, "-m", "mypy", "src"]
        result = await command_runner.run_command(
            argv, timeout_seconds=timeout_seconds, cwd=str(expra_root), max_output_bytes=2 * 1024 * 1024
        )
        log_path = _write_log(log_dir, "mypy.log", argv, result)
        error_lines = [line for line in result.stdout.splitlines() if ": error:" in line]
        return {
            "profile": profile,
            "success": result.exit_code == 0 and not result.timed_out,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": time.monotonic() - start,
            "failed": len(error_lines),
            "failure_summaries": error_lines[:50],
            "log_path": str(log_path),
        }

    if profile == "compileall":
        argv = [executable, "-m", "compileall", "-q", "src"]
        result = await command_runner.run_command(
            argv, timeout_seconds=timeout_seconds, cwd=str(expra_root), max_output_bytes=1024 * 1024
        )
        log_path = _write_log(log_dir, "compileall.log", argv, result)
        return {
            "profile": profile,
            "success": result.exit_code == 0 and not result.timed_out,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": time.monotonic() - start,
            "failure_summaries": [line for line in result.stdout.splitlines() if line.strip()][:50],
            "log_path": str(log_path),
        }

    if profile == "diff_check":
        result = await git_utils.run_git(expra_root, ["diff", "--check"], timeout_seconds=timeout_seconds)
        log_path = _write_log(log_dir, "diff_check.log", ["git", "diff", "--check"], result)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return {
            "profile": profile,
            "success": result.ok,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": time.monotonic() - start,
            "failure_summaries": lines[:50],
            "log_path": str(log_path),
        }

    if profile == "build_wheel":
        argv = [executable, "-m", "build", "--wheel"]
        result = await command_runner.run_command(
            argv, timeout_seconds=timeout_seconds, cwd=str(expra_root), max_output_bytes=1024 * 1024
        )
        log_path = _write_log(log_dir, "build_wheel.log", argv, result)
        artifact_match = re.search(r"Successfully built (\S+\.whl)", result.stdout)
        artifact_path = str(expra_root / "dist" / artifact_match.group(1)) if artifact_match else None
        return {
            "profile": profile,
            "success": result.exit_code == 0 and not result.timed_out,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": time.monotonic() - start,
            "log_path": str(log_path),
            "artifact_path": artifact_path,
        }

    raise RunChecksError(f"unimplemented run_checks profile: {profile!r}")
