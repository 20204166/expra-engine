# Performance Baseline

This is the append-only performance baseline for Expra. Add one new row for
each released version; do not revise earlier rows. Keep the observation
workloads and iteration counts unchanged unless the table records the change.

## Baseline Table

| Version | Date | Source commit | Render stress | Resource cache | Editor redraw | Overall |
| --- | --- | --- | --- | --- | --- | --- |
| 0.4.7.0 | 2026-09-24 | `111c612de0ec` | 20 iterations, 2.834043 s; cache `0 -> 3`; handlers `0 -> 0`; diagnostics `0 unique / 0 total`; memory delta `+305.18 KiB` | 15 iterations, 2 assets, 0.008399 s; cache `0 -> 2` | 15 iterations, 0.776810 s; Canvas items `115 -> 115`; PhotoImages `27 -> 27`; handlers `0 -> 0`; diagnostics `0` | `bounded` for all probes |

## Observability Baseline

This is the first complete observability snapshot. Append one row for each
future version and preserve the same checks where applicable.

| Version | Date | Snapshot status | Edit render | Runtime render | Runtime behaviour | Asset and diagnostics evidence |
| --- | --- | --- | --- | --- | --- | --- |
| 0.4.7.0 | 2026-09-24 | **Baseline 1: complete** | 60 render items; 3 textures; pixel renderer success; 0 failures; 0 diagnostics; SHA-256 `987628af...f6ca16`; run `1790247376-a6601dff` | 60 render items; 3 textures; pixel renderer success; 0 failures; 0 diagnostics; SHA-256 `987628af...f6ca16`; run `1790247376-807b83ba` | Project code executed; Play, tick, `W` key down/up, entity inspection, render inspection, and Stop all passed. `Operative` moved from `(-34.0, -14.0)` to `(-34.0, -11.25)` after `0.25 s`. | `player_survivor_gun.png` decoded successfully at `51x43` with alpha; content hash `b16c1208...df90e0`; no provider failure. Both performance probes and editor redraw probe were `bounded`. |

## Observation Context

- Project: `examples/blacksite_relay` (`66` entities).
- Render-stress workload: 20 headless render iterations with memory tracking.
- Resource-cache workload: 15 resolutions each for two assets:
  `assets://kenney/player_survivor_gun.png` and
  `assets://kenney/zombie.png`.
- Editor-redraw workload: 15 redraws against the live Tk editor viewport.
- Editor session size: `980x640`.
- Environment: Linux, Python `3.12.3`, Pygame `2.6.1`, Tk `8.6`.
- Measurements were produced by the real `performance_probe` implementation.
- The complete observability snapshot used the real `render_snapshot`,
  `runtime_probe`, `resource_trace`, and renderer capability inspectors.

## Interpretation

- `bounded` means the measured retained-resource counts did not grow beyond
  the expected loaded-resource set during the probe.
- The render-stress memory value is a tracemalloc delta for that run, not a
  leak claim by itself.
- Durations are machine and environment dependent. Compare them only with
  matching workloads and note environment changes alongside future rows.
