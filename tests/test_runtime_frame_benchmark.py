"""Contract checks for the frozen real-runtime frame benchmark CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from expra_engine.core.component import TransformComponent
from tools.runtime_frame_benchmark import _build_scene, _validate_resume_report

_BENCHMARK = Path(__file__).parents[1] / "tools" / "runtime_frame_benchmark.py"


def test_description_reports_the_fixed_end_to_end_acceptance_contract() -> None:
    result = subprocess.run(
        [sys.executable, str(_BENCHMARK), "--describe"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    description = json.loads(result.stdout)
    assert description["target_p95_ms"] == {
        "1000": 10.0,
        "5000": 20.0,
        "10000": 50.0,
        "50000": 70.0,
    }
    assert description["resolution"] == [1280, 800]
    assert description["runs_per_size"] == 3
    assert description["warmup_frames"] >= 30
    assert description["measured_frames"] >= 120
    assert description["workloads"] == ["large-world", "visible-density"]


def test_benchmark_refuses_to_lower_acceptance_sample_minimums() -> None:
    result = subprocess.run(
        [sys.executable, str(_BENCHMARK), "--warmup-frames", "2"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "at least 30" in result.stderr


def test_resume_requires_a_checkpoint_path() -> None:
    result = subprocess.run(
        [sys.executable, str(_BENCHMARK), "--resume"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--resume requires --output" in result.stderr


def test_resume_report_requires_matching_baseline_and_matrix() -> None:
    matrix_scope = {
        "workloads": ["large-world"],
        "entity_counts": [1_000],
        "runs_per_case": 3,
    }
    report = {
        "baseline_commit": "abc123",
        "source_fingerprint": "source-a",
        "contract": {},
        "matrix_scope": matrix_scope,
        "results": [],
    }
    assert _validate_resume_report(
        report,
        baseline_commit="abc123",
        source_fingerprint="source-a",
        contract={},
        matrix_scope=matrix_scope,
    ) == []

    with pytest.raises(ValueError, match="baseline commit"):
        _validate_resume_report(
            report,
            baseline_commit="different",
            source_fingerprint="source-a",
            contract={},
            matrix_scope=matrix_scope,
        )
    with pytest.raises(ValueError, match="matrix scope"):
        _validate_resume_report(
            report,
            baseline_commit="abc123",
            source_fingerprint="source-a",
            contract={},
            matrix_scope={**matrix_scope, "workloads": ["visible-density"]},
        )
    with pytest.raises(ValueError, match="source fingerprint"):
        _validate_resume_report(
            report,
            baseline_commit="abc123",
            source_fingerprint="source-b",
            contract={},
            matrix_scope=matrix_scope,
        )


def test_workload_fixture_has_fixed_mix_counts_and_deterministic_positions() -> None:
    large, large_details = _build_scene(1_000, "large-world", "assets://probe.png")
    large_again, _ = _build_scene(1_000, "large-world", "assets://probe.png")
    dense, dense_details = _build_scene(1_000, "visible-density", "assets://probe.png")

    assert len(large.entities) == len(dense.entities) == 1_000
    assert large_details["component_counts"] == {
        "animated_sprite": 50,
        "collider": 10,
        "nonvisual": 150,
        "primitive": 600,
        "sprite": 200,
    }
    assert large_details["dynamic_entities"] == dense_details["dynamic_entities"] == 50
    assert large_details["behavior_components"] == 5
    assert large_details["lights"] == dense_details["lights"] == 1
    assert large_details["hud_roots"] == dense_details["hud_roots"] == 1
    assert large_details["screen_effect_components"] == 2
    assert [entity.to_dict() for entity in large.entities] == [
        entity.to_dict() for entity in large_again.entities
    ]
    def x_positions(scene):
        positions = []
        for entity in scene.entities:
            transform = entity.get_component(TransformComponent)
            if transform is not None:
                positions.append(transform.x)
        return positions

    large_positions = x_positions(large)
    dense_positions = x_positions(dense)
    assert max(large_positions) - min(large_positions) > 100.0
    assert max(dense_positions) - min(dense_positions) < 32.0
