# Extraction Map: System Analyzer → Expra Engine

## Classification Legend

| Class | Meaning |
|---|---|
| A | Directly reusable — copied verbatim, import paths updated |
| B | Reusable after stripping SA domain meaning |
| C | Useful mechanism embedded in domain code — not extracted |
| D | SA-specific — not copied |

## Component Map

| SA Source | Class | Expra Engine Destination | Changes Made |
|---|---|---|---|
| `maintenance/observability.py` | A | `src/expra_engine/observability.py` | Import paths only |
| `maintenance/ui/transition.py` | A | `src/expra_engine/coordinators/transition.py` | Import paths only |
| `maintenance/ui/window_supports/timer_delivery.py` | A | `src/expra_engine/ui/timer_delivery.py` | Import paths only |
| `maintenance/ui/action_coordinator.py` | A | `src/expra_engine/coordinators/button_coordinator.py` | Import paths + renamed |
| `maintenance/ui/render_coordinator.py` | A | `src/expra_engine/coordinators/ui_coordinator.py` | Import paths only |
| `maintenance/components/coordinator.py` (AppCoordinator) | B | `src/expra_engine/coordinators/app_coordinator.py` | Removed discovery/placement logic |
| `maintenance/components/coordinator.py` (ComponentRefreshScheduler) | B | `src/expra_engine/coordinators/refresh_scheduler.py` | Removed CPU/GPU key meaning |
| `maintenance/ui/styles.py` | B | `src/expra_engine/ui/styles.py` | Replaced SA page names with editor names |
| `maintenance/ui/layout.py` | B | `src/expra_engine/ui/layout.py` | Removed thermal_graph import |
| `maintenance/ui/navigation.py` (PageRouter) | B | `src/expra_engine/ui/navigation.py` | Renamed PageRouter → PanelRouter |
| SA scanner modules | D | — | Not extracted |
| SA cluster/pairing modules | D | — | Not extracted (separate repo) |
| SA networking/TLS modules | D | — | Not extracted (separate repo) |
| SA page implementations | D | — | Not extracted |

## New Code (No SA Source)

| File | Purpose |
|---|---|
| `src/expra_engine/core/component.py` | Component base class + TransformComponent |
| `src/expra_engine/core/entity.py` | Entity with stable UUID, component list |
| `src/expra_engine/core/scene.py` | Scene container + serialization |
| `src/expra_engine/core/project.py` | File-backed project model |
| `src/expra_engine/core/engine.py` | Engine run state + scene isolation |
| `src/expra_engine/ui/toolbar.py` | Editor toolbar with play/pause/stop |
| `src/expra_engine/ui/hierarchy.py` | Entity hierarchy panel |
| `src/expra_engine/ui/inspector.py` | Component inspector panel |
| `src/expra_engine/ui/viewport.py` | Canvas viewport |
| `src/expra_engine/ui/console.py` | Log console |
| `src/expra_engine/ui/editor_window.py` | Composition root |
| `src/expra_engine/main.py` | Entry point |

## What Was NOT Extracted

- `PlacementPolicy`, `PlacementDecision`, `PlacementRequest` — cluster-specific, removed from AppCoordinator
- `start_discovery`, `stop_discovery`, `discovery_tick` — Zeroconf/mDNS, excluded (separate networking repo)
- `BackgroundOrchestrator` — useful mechanism, but too tightly coupled to SA lifecycle to extract cleanly
- All SA scanner implementations (CPU, GPU, memory, network, storage, battery)
- All SA page layouts (SystemOverviewPage, NodeAndConnectionsPage, etc.)
- All cluster/pairing/TLS code — reserved for networking repo
