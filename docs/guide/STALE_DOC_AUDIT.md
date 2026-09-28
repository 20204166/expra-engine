# Stale Doc Audit

Freshness of the older documents at the `docs/` root, relative to the current
source (commit `fa774e8`). Status: **accurate** / **partial** / **stale** /
**historical**.

| File | Status | Notes | Action |
|---|---|---|---|
| `ARCHITECTURE.md` | partial | Ownership matrix and threading model are accurate, but the "Future: Game Export *(not implemented)*" section is **stale** — export is fully implemented. | Superseded by `guide/ARCHITECTURE.md`. |
| `PROJECTS.md` | partial | Mostly correct; still references the legacy `scenes/main.json` layout; the canonical format is now `.pb`. | Superseded by `guide/PROJECTS.md`. |
| `SCRIPTING.md` | accurate | Matches current behaviour API. | Merged into `guide/BEHAVIOURS_AND_SCRIPTING.md`. |
| `SCRIPTING_SOURCE_AUDIT.md` | historical | Records baseline at commit `783f051`. | Retain as history. |
| `FILESYSTEM.md` | accurate | Matches current filesystem API. | Merged into `guide/RESOURCES_AND_ASSETS.md`. |
| `THREADING.md` | accurate | Threading invariant holds; one diagram shows the older `after_idle` deliver path while the current path is `TkDeliveryQueue` (25 ms poll) — a minor discrepancy. | Retain; see `guide/ARCHITECTURE.md`. |
| `DEVELOPMENT_MCP.md` | accurate | Detailed and current MCP description. | Merged (condensed) into `guide/MCP_AND_DEBUGGING.md`. |
| `GAME_EXPORT_FUTURE.md` | partial | Filename says "FUTURE" but the export subsystem is implemented; the "deferred" section (macOS, single-file, general dep resolution) is still accurate. | Retain; see `guide/EXPORT.md`. |
| `GAME_UI_FUTURE.md` | accurate | Correctly documents an unimplemented future runtime UI. | Retain; see `guide/UI.md`. |
| `PERFORMANCE_BASELINE.md` | historical | Append-only baseline at `0.4.7.0` (`111c612`). | Merged into `guide/PERFORMANCE.md`. |
| `MINIPYENGINE_INTEGRATION_MAP.md` | historical | Reference-engine mapping note. | Retain. |
| `PPB_INTEGRATION_MAP.md` | historical | Reference-engine mapping note. | Retain. |
| `URSINA_INTEGRATION_MAP.md` | historical | Reference-engine mapping note. | Retain. |
| `POLISH_EXTRACTION_MAP.md` | historical | Editor-polish extraction note. | Retain. |
| `SPACE_PONG_DOGFOOD.md` / `_EVALUATION.md` / `_FINAL_REPORT.md` | historical | Project-evaluation notes. | Retain. |

## Conflicts resolved

- **Game export**: the old `ARCHITECTURE.md` says "not implemented"; the current
  source has a complete `export/` subsystem. `guide/ARCHITECTURE.md` and
  `guide/EXPORT.md` describe it as implemented.
- **Document format**: `PROJECTS.md` shows `.json` as the norm; the canonical
  persisted format is `.pb`. `guide/DOCUMENT_MODEL.md` is authoritative.

No contradictory "official" pages remain: each topic has a single canonical
page in `docs/guide/`, and the `docs/` root files are historical/superseded.
