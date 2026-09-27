"""Authored World transition presentation state machine."""

import pytest

from expra_engine.core.world import TransitionMode
from expra_engine.runtime.world_transition import (
    TransitionStatus,
    WorldTransitionController,
)


def test_fade_waits_for_readiness_fades_out_switches_then_fades_in() -> None:
    transition = WorldTransitionController(fade_duration=0.2)
    transition.begin("town-forest", "town", "forest", TransitionMode.FADE)

    assert transition.status is TransitionStatus.PREPARING
    assert transition.alpha == 0.0
    assert not transition.advance(0.1)
    transition.destination_ready()
    assert transition.status is TransitionStatus.FADING_OUT
    assert transition.alpha == 0.0
    assert not transition.advance(0.1)
    assert transition.advance(0.1)
    assert transition.status is TransitionStatus.SWITCHING
    assert transition.alpha == 1.0

    transition.complete_switch()
    assert transition.status is TransitionStatus.FADING_IN
    assert transition.alpha == 1.0
    assert not transition.advance(0.1)
    assert transition.alpha == 0.5
    assert not transition.advance(0.1)
    assert transition.status is TransitionStatus.COMPLETE
    assert transition.alpha == 0.0


@pytest.mark.parametrize(
    "mode", [TransitionMode.SEAMLESS, TransitionMode.INSTANT, TransitionMode.LOADING]
)
def test_nonfade_modes_switch_immediately_once_destination_is_ready(mode) -> None:
    transition = WorldTransitionController()
    transition.begin("route", "town", "forest", mode)
    transition.destination_ready()

    assert transition.status is TransitionStatus.SWITCHING
    assert transition.advance(0.0)
    transition.complete_switch()
    assert transition.status is TransitionStatus.COMPLETE
    assert transition.alpha == 0.0


def test_destination_failure_never_requests_switch_or_fades_into_invalid_level() -> None:
    transition = WorldTransitionController(fade_duration=0.1)
    transition.begin("route", "town", "forest", TransitionMode.FADE)
    transition.fail("destination failed")

    assert transition.status is TransitionStatus.FAILED
    assert transition.error == "destination failed"
    assert transition.alpha == 0.0
    assert not transition.advance(1.0)


def test_failure_during_fade_switch_returns_to_source_before_failed_terminal_state() -> None:
    transition = WorldTransitionController(fade_duration=0.1)
    transition.begin("route", "town", "forest", TransitionMode.FADE)
    transition.destination_ready()
    assert transition.advance(0.1)
    transition.fail("activation failed")

    assert transition.status is TransitionStatus.FADING_IN
    assert transition.alpha == 1.0
    transition.advance(0.1)
    assert transition.status is TransitionStatus.FAILED
