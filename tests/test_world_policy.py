"""Residency policy has one canonical owner with compatibility re-exports."""

from expra_engine.runtime import world_streaming
from expra_engine.runtime.world_policy import (
    LevelResidencyManager,
    LevelResidencyState,
    WorldStreamingPolicy,
)


def test_world_streaming_policy_and_residency_types_have_canonical_policy_owner() -> None:
    assert world_streaming.WorldStreamingPolicy is WorldStreamingPolicy
    assert world_streaming.LevelResidencyManager is LevelResidencyManager
    assert world_streaming.LevelResidencyState is LevelResidencyState
    assert WorldStreamingPolicy.__module__ == "expra_engine.runtime.world_policy"
