# MCP and Debugging

## MCP server

The Expra MCP server (`tools/expra_mcp/`) exposes Expra as tools to an AI
assistant. The server process **never imports `expra_engine`**; it drives Expra
through subprocesses (`_static_runner.py` for static ops, `_editor_worker.py`
for editor sessions), so Expra-side state is isolated per call.

### Configuration

Resolved from `--config` → `$EXPRA_MCP_CONFIG` → `./.expra-mcp.toml` →
`~/.config/expra-mcp/config.toml`. Key settings:

- `workspace.expra_root`, `workspace.default_project`, `workspace.python`.
- `workspace.trusted_project_roots` (default `["examples"]`) — gates tools that
  execute project code.
- `execution.allow_source_writes` (default false), `execution.allow_network`
  (default false — gates `export_inspect(action="export")`).
- `editor.display_mode` (`auto`/`native`/`xvfb`), `artifacts.directory`,
  `diagnostics.directory`.

### Tool inventory

| Tool | Purpose | Executes project code? |
|---|---|---|
| `workspace_doctor` | report interpreter/pygame/Tk/dev-tools/reference status + readiness | no |
| `repo_inspect` | read-only git introspection of Expra tree (status/diff/log/head) | no |
| `source_search` | literal/regex search across the six source roots | no |
| `source_read` | bounded line-numbered read from a source root | no |
| `expra_inspect` | static project/scene/entity/component/world inspection | no (data parsing only) |
| `render_inspect` | trace render pipeline via real `extract_render_frame` + `RenderPlanBuilder` | no |
| `resource_trace` | trace one asset end-to-end (id → path → hash → Pygame decode) | no |
| `render_snapshot` | render edit/runtime frame to an actual image (+ pixel diff) | no |
| `diagnostics_analyze` | aggregate a render run's diagnostics into failure signatures | no |
| `performance_probe` | bounded-retry vs leak measurements (render/resource/document/editor redraw) | no |
| `runtime_probe` | drive a real headless Engine through a step sequence | **yes** (gated) |
| `editor_session` | operate a real Tk EditorWindow worker | **yes** (gated on open_project) |
| `export_inspect` | drive the real exporter (`plan`/`verify`/`export`) | gated |
| `run_checks` | run named dev-check profiles (tests/lint/type) | no (only own test dir) |

Gated tools refuse anything outside `trusted_project_roots`; `export` also
requires `allow_network`.

### CLI

```
expra-mcp serve --transport stdio|http
expra-mcp doctor
expra-mcp init --expra PATH --default-project NAME --reference ID=PATH
expra-mcp config show | validate | emit <client> --write
```

## Observability

`ObservabilityWatcher` (`observability.py`) records bounded, thread-safe metrics
with free-form string targets (conventionally `app:…`, `ui:…`, `runtime:…`,
`render:…`, `editor:…`). Methods: `begin`/`finish`, `record`, `record_event`,
`increment`, `set_gauge`, `snapshot`, `reset`. Events include `coalesced`,
`stale`, `rejected`, `cache_hit`.

## Debugging workflow

A typical renderer issue: `workspace_doctor` → `expra_inspect` →
`render_inspect` → `resource_trace` → `render_snapshot` → `diagnostics_analyze`
→ `runtime_probe`/`editor_session`. The server ships four prompts
(`debug-renderer`, `mine-reference`, `tk-regression`, `release-check`) encoding
these workflows.
