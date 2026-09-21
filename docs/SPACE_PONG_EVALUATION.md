# Space Pong Evaluation

Date: 2026-09-21

This evaluation separates engine defects from project tuning. Evidence includes
the live editor screenshots at 1920x1080 and the installed-wheel test runs.

## Current Verdict

Space Pong is now a playable engine dogfood project rather than only a render
fixture. The editor frames the 100x60 arena, displays the score HUD, runs the
project behaviour, routes configured keyboard actions, and preserves the scene
on Stop. The current visual language is deliberate: dark navy playfield, cyan
left player, magenta right player, and a thin cyan centre line.

## Findings

| Finding | Owner | Severity | Status |
| --- | --- | --- | --- |
| Script-only `Game Controller` appeared as a centre marker in the viewport | Engine/editor | High | Fixed in working tree; regression added |
| Float text sizes such as `8.0` caused Tk render failures | Engine/editor | High | Fixed in 0.3.2.0 |
| Editor Play mode did not forward keyboard input | Engine/editor | Critical | Fixed in 0.3.2.1 |
| Ball was too fast for manual play | Space Pong example | Medium | Tuned from 34 to 18 |
| Entity name labels add clutter over the playfield | Editor presentation | Low | Accepted for now; runtime is unaffected |

The `Game Controller` is valid in the hierarchy and Inspector because it owns
the project behaviour. It should not be drawn in the viewport when it has no
transform or visual component. Its previous centre marker was an editor bug,
not a game-content requirement.

## Gameplay Evaluation

- Full arena framing and score values are visible in Play mode.
- Left and right paddles use project-configured actions (`W/S` and arrows).
- Ball movement, wall bounce, paddle collision, scoring, pause, restart, and
  winning state are covered by project tests.
- Ball speed `18.0` is the current playable default; paddle speed remains a
  project-owned tuning value.
- The runtime uses generic extraction and Pygame contracts; no Space Pong
  branch exists in engine rendering or input code.

## Fault Ownership

Engine tests should fault on generic failures: invalid render values, stale
render targets, missing input routing, camera framing, malformed components,
and renderer/runtime exceptions. Project tests should fault on ball speed,
score rules, winning state, HUD text, collision policy, and scene composition.

Observability currently covers bounded coordinator/refresh metrics, render
failure isolation, event counts, and duration distributions. It does not yet
record ball trajectories, input drops, frame-time spikes, or score transitions.
Those are the next useful signals for diagnosing a visual or gameplay report.

## Capability Timeline

| Version | Capability milestone |
| --- | --- |
| 0.2.5.0 | Previous baseline used for comparison |
| 0.3.1.0 | Scene camera settings and large-world editor framing |
| 0.3.2.0 | Tk-safe integer text rendering; float text regression coverage |
| 0.3.2.1 | Generic editor keyboard input bridge and input edge-case coverage |
| 0.3.4.0 | Script-only marker suppression and playable ball-speed tuning |

## Verification Evidence

- Full suite: `1309 passed`, `157 subtests passed` after the marker and speed
  changes.
- Space Pong after speed tuning: `8 passed`.
- Editor, renderer, runtime, input, and observability checks all passed before
  the latest marker change.
- Installed wheel: `0.3.4.0`; checksum is recorded in `dist/SHA256SUMS`.
