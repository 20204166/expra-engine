# Expra Development MCP Server

**MCP is development tooling. Exported games do not depend on MCP.**

`expra-mcp` (`tools/expra_mcp/`) is a local Model Context Protocol server
that lets a coding agent investigate the Expra working tree through
structured evidence — real environment identity, real source access to
Expra and five reference engines, real renderer output, a real headless
engine, and a real live editor session — instead of pasted screenshots,
terminal logs, or assumptions.

It is a real MCP server built on the official `mcp` Python SDK (v2, pinned
`mcp>=2.2,<3`), not a JSON-RPC lookalike: genuine `tools/list`, `tools/call`,
`resources/list`, `resources/read`, `prompts/list`, `prompts/get`, real
`ImageContent`, and both `stdio` and Streamable HTTP transports, verified
against the official SDK `Client` (in-process and over real subprocess/HTTP
connections) and against OpenCode as a real host.

## Architecture

```
MCP Client (OpenCode, Claude Code, ...)
    |
    v
expra-mcp server process (this server's own Python venv)
    |  -- NEVER imports expra_engine directly (see "Environment identity" below)
    |
    +-- one-shot ops (expra_inspect, resource_trace, render_inspect,
    |   render_snapshot, runtime_probe, export_inspect, performance_probe):
    |       subprocess -> _static_runner.py, run under the CONFIGURED
    |       Expra interpreter, one JSON request in on stdin -> one JSON
    |       response out on stdout, process exits
    |
    +-- run_checks: subprocess -> pytest/ruff/pyright/mypy/git/build,
    |       argument arrays only, never shell=True
    |
    +-- editor_session: long-lived subprocess -> _editor_worker.py, run
            under the CONFIGURED Expra interpreter, owns a REAL Tk
            EditorWindow on its own main thread, driven by a
            newline-delimited JSON command protocol over stdin/stdout for
            the life of the session
```

Two independent runner scripts (`_static_runner.py`, `_editor_worker.py`)
duplicate a handful of small helper functions rather than importing each
other or `expra_dev_mcp` — both are invoked as standalone subprocesses under
whatever Python has `expra_engine` installed, which may not be the same
Python (or even the same machine's dependency set) as the one running the
MCP server itself.

## Environment identity ("which Expra is actually running?")

This is the server's founding constraint, driven by a real class of bug
that motivated this whole project: source working tree, installed Expra
package, launcher Python, and Pygame installation can silently diverge.

`expra-mcp`'s own process **never** does `import expra_engine`. Every tool
that needs Expra internals runs a subprocess under the *configured* Expra
interpreter (`workspace.python = "auto"` resolves to
`<expra_root>/.venv/bin/python` if it exists, else falls back to the
current interpreter with that fact reported, never silently). This means
`expra-mcp` keeps working even when Expra's own environment is broken, and
`workspace_doctor` can prove — not assume — which `expra_engine.__file__`,
which `pygame`, and which git commit are actually in play.

Call `workspace_doctor` before any environment-sensitive debugging. It
returns `READY` / `READY_WITH_LIMITATIONS` / `NOT_READY` with structured
reasons, and explicitly flags when `expra_engine` imports from anywhere
other than `<expra_root>/src`.

## Security model

- **No arbitrary shell, anywhere.** Every subprocess call is an argument
  array (`asyncio.create_subprocess_exec`, never `shell=True`). `run_checks`
  only exposes named profiles, never a raw command string.
- **Reference repos (`godot`, `ppb`, `minipy`, `ursina`, `exp_ui`) are
  read-only in code**, regardless of what config claims — enforced in
  `source_access.py`'s containment check, not just documented convention.
- **Path containment** (NUL bytes, absolute-path escapes, `..`/symlink
  escapes) is enforced for every source tool and the `source://` resource
  template, and independently for `run_checks(profile='focused')`'s
  `test_target`.
- **Trusted project roots.** Only `runtime_probe`, `editor_session`, and
  `export_inspect`'s `plan`/`export` actions execute project-authored
  Python (Behaviour scripts via the real `ScriptRegistry.importlib` path).
  These are gated to `workspace.trusted_project_roots` (default: exactly
  `examples/` — confirmed the only real project directories in this repo).
  Every purely static tool (`expra_inspect`, `render_inspect`,
  `resource_trace`, `render_snapshot`) is confirmed, by reading the actual
  `Project.load`/`Scene.from_dict`/`extract_render_frame` source, to never
  execute project code — every one of their results reports
  `executed_project_code: false` truthfully, not by assertion.
- **Network access is opt-in.** `export_inspect(action='export')` actually
  downloads a Python runtime and packages (`GameExporter.export()` ->
  `packager.install_runtime`/`install_packages`) — discovered mid-
  implementation that this is not a lightweight inspection. It is refused
  outright unless `execution.allow_network = true` is set; `action='plan'`
  validates configuration without that cost, and `action='verify'` inspects
  an already-built directory read-only.
- **No source-editing tool.** The coding agent already has file-edit tools;
  this server's job is evidence, not another way to write code.
- **stdout is protocol-clean, always.** Every runner script sets
  `PYGAME_HIDE_SUPPORT_PROMPT=1` before importing pygame (its community
  banner would otherwise corrupt the single-JSON-line contract — a real bug
  caught live during Phase 2D) and configures logging to stderr only.
  `editor_session`'s headless Xvfb fallback manages its own `Xvfb :N`
  process directly rather than shelling out to `xvfb-run`, because that
  wrapper script runs the wrapped command as `"$@" 2>&1` — merging stderr
  into stdout — which would have silently broken the same contract the
  moment expra_engine logged anything (confirmed by reading
  `/usr/bin/xvfb-run` after a real hang during testing).

## Installation

```bash
cd tools/expra_mcp
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/expra-mcp init \
    --expra /path/to/expra-engine \
    --default-project examples/blacksite_relay \
    --reference godot=/path/to/godot-master \
    --reference ppb=/path/to/pursuedpybear-canon \
    --reference minipy=/path/to/MiniPyEngine-main \
    --reference ursina=/path/to/ursina-master \
    --reference exp_ui=/path/to/exp
```

`init` writes `./.expra-mcp.toml` (gitignored — machine-local absolute
paths) and immediately runs `doctor` against it. `.expra-mcp.example.toml`
at the repo root is the tracked, illustrative counterpart.

## Configuration

TOML, `schema_version = 1`. Discovery order: `--config` >
`$EXPRA_MCP_CONFIG` > `./.expra-mcp.toml` > OS user config directory
(`~/.config/expra-mcp/config.toml` on Linux). `${ENV}` substitution and `~`
expansion apply to path-shaped values; relative paths resolve against the
config file's own directory.

```toml
schema_version = 1

[workspace]
expra_root = "/path/to/expra-engine"
default_project = "examples/blacksite_relay"
python = "auto"                          # or an explicit interpreter path
trusted_project_roots = ["examples"]     # gates runtime_probe/editor_session/export

[references.godot]
path = "/path/to/godot-master"
read_only = true                          # enforced in code regardless of this value
domains = ["rendering", "editor", "resources", "physics", "audio", "animation"]

# ... ppb, minipy, ursina, exp_ui likewise ...

[execution]
allow_source_writes = false
allow_network = false                     # must be true for export_inspect(action="export")
command_timeout_seconds = 600
max_output_kb = 256
max_parallel_commands = 2

[editor]
display_mode = "auto"                     # "auto" | "native" | "xvfb"
default_width = 1280
default_height = 720
session_timeout_seconds = 1800

[artifacts]
directory = ".expra-mcp/artifacts"        # render_snapshot PNGs, keyed by run_id

[diagnostics]
directory = ".expra-mcp/runs"             # captured log records for diagnostics_analyze
deduplicate = true
```

CLI: `expra-mcp doctor` / `config show` / `config validate` /
`config emit <client> [--scope project|user] [--write]`.

## Reference-repo mapping

| ID | Path | Use for | Never |
|---|---|---|---|
| `expra` | `<expra_root>` | authoritative current source, read-write via normal file tools (not this server) | — |
| `godot` | Godot Engine checkout | mature 2D rendering/resource/editor concepts | porting RID/RenderingDevice/GLES machinery |
| `ppb` | PursuedPyBear checkout | Python game loop, event dispatch, scene lifecycle | reintroducing what Expra already adapted |
| `minipy` | MiniPyEngine checkout | small-engine ergonomics comparison | treating as an authority |
| `ursina` | Ursina checkout | entity/camera/input API ergonomics | introducing a Panda3D/Ursina dependency |
| `exp_ui` | original `/exp` Tk app | `AppCoordinator`/`UICoordinator`, Tk main-thread invariants, scheduling/cancellation/shutdown | — |

All five reference repos on this development machine are plain extracted
trees, not git checkouts — `source_read`'s `revision` field correctly
reports `null` for them rather than fabricating one.

## Tool catalog (14 tools)

| Tool | Phase | Executes project code? |
|---|---|---|
| `workspace_doctor` | 2A | no |
| `source_search`, `source_read`, `repo_inspect` | 2B | no |
| `expra_inspect`, `render_inspect`, `resource_trace` | 2C | no |
| `render_snapshot`, `diagnostics_analyze` | 2D | no |
| `runtime_probe` | 2E | **yes** (Behaviour scripts, via `ScriptRegistry`) |
| `run_checks`, `export_inspect` | 2E | `export_inspect(action="export")` runs project code indirectly by packaging it; `plan`/`verify` do not |
| `editor_session` | 2F | **yes** (`open_project`) |
| `performance_probe` | 2G | no |

Plus 1 resource template (`source://{repo}/{path}`) and 4 prompts
(`debug-renderer`, `mine-reference`, `tk-regression`, `release-check`).

Every tool that does NOT execute project code reports
`executed_project_code: false` in its result — verified against the actual
`Project.load`/`Scene.from_dict`/`Entity.from_dict` source, which are pure
JSON parsing, and confirmed that even the `script` component type only
stores `script_id`/`behaviour_class`/`exposed_values` as data without ever
importing the referenced module.

## Client setup

`expra-mcp config emit <client>` prints by default; `--write` is the only
path that mutates a file. Each schema below was verified against that
client's real current documentation, not assumed from the original design
spec's illustrative examples (which turned out to differ in at least one
case — see the OpenCode note).

### OpenCode (priority client)

```bash
.venv/bin/expra-mcp config emit opencode --write   # writes ./opencode.json
opencode mcp list                                   # should show "expra connected"
```

Real schema (verified against OpenCode 1.18.32's actual config, **not**
the design spec's illustrative example): top-level `mcp.servers.<name>`
with `type: "local"`, `command` as a single array, `cwd`, `environment`,
`enabled`. There is **no `protocol` field** — that was in the original
spec's example but does not exist in OpenCode's real schema.

### VS Code

```bash
.venv/bin/expra-mcp config emit vscode --write   # writes ./.vscode/mcp.json
```

Top-level key is `servers` (not `mcpServers`), `type: "stdio"`, `command`
as a string, `args` as an array, `env` as an object.

### Cursor

```bash
.venv/bin/expra-mcp config emit cursor --write --scope project   # ./.cursor/mcp.json
.venv/bin/expra-mcp config emit cursor --write --scope user      # ~/.cursor/mcp.json
```

Top-level key is `mcpServers`, `command`/`args`/`env` per server.

### Claude Code

```bash
.venv/bin/expra-mcp config emit claude-code --scope project
```

Prints the real `claude mcp add ... -- <command> <args...>` invocation
(the `--` separator between Claude's own flags and the server command is
required) plus the resulting `.mcp.json`/`~/.claude.json` shape. Never
executed automatically.

### Codex

```bash
.venv/bin/expra-mcp config emit codex
```

Prints the real `codex mcp add expra --env ... -- <command> <args...>`
invocation plus the resulting `config.toml` block
(`[mcp_servers.expra]` with `args` as an array and a nested
`[mcp_servers.expra.env]` table). Never executed automatically.

### Generic

```bash
.venv/bin/expra-mcp config emit generic
```

Prints both stdio and Streamable HTTP connection details for any other MCP
client.

## Transports

- `expra-mcp serve --transport stdio` (default) — no ports, no auth,
  preferred for local development.
- `expra-mcp serve --transport http --host 127.0.0.1 --port 8000` — binds
  loopback-only by default; never exposed on `0.0.0.0` without an explicit,
  separate decision by whoever deploys it.

Both verified end-to-end against the official SDK `Client`: real `tools/list`
+ `tools/call` over a real stdio child process and over a real HTTP
connection, negotiating the modern MCP protocol version automatically (SDK-
owned, never hand-rolled handshake logic).

## Platform notes

- **Linux** (this development machine): both `editor_session` display
  paths verified end-to-end — native `DISPLAY=:0` and a self-managed
  `Xvfb :N` process (not `xvfb-run`, see "Security model" above) for
  headless/CI use. `display_mode = "auto"` picks whichever is usable;
  `"native"`/`"xvfb"` force one or the other.
- **Windows**: `workspace.python = "auto"` resolves to
  `.venv\Scripts\python.exe`; no Xvfb assumption; all path handling goes
  through `pathlib`, never `/`-string concatenation. Implemented per the
  original design constraints; not independently verified on this
  Linux-only development machine.
- **macOS**: native Tk, no X11 assumption. Same caveat — implemented, not
  independently verified here.
- **WSL**: run the MCP server in the same filesystem/environment as the
  repositories when possible; if a Windows client must launch a WSL
  server, the config generator's printed command is the thing to wrap in
  `wsl.exe`, not something this server does automatically.

## Troubleshooting

- **`workspace_doctor` reports `NOT_READY`**: read its `reasons` list —
  it will name the exact mismatch (e.g. `expra_engine` importing from a
  stale installed package instead of `<expra_root>/src`).
- **`editor_session(action="start")` returns
  `editor_session_available: false`**: read `reason` — it will say either
  "no usable `$DISPLAY` and `xvfb-run`/`Xvfb` not on PATH" or a genuine Tk
  construction failure, never a silent hang.
- **A `render_snapshot`/`runtime_probe` call reports repeated failures**:
  follow up with `diagnostics_analyze(run_id=...)` rather than reading raw
  logs — it aggregates by `(logger, level, message_template)` signature
  with counts and first/last timestamps.
- **Suspected memory/resource leak**: use `performance_probe`, not
  assumption — it reports `bounded` / `growing` / `inconclusive` backed by
  real before/after measurements (resource cache size, logger handler
  count, Canvas item count, `Tcl image names` count, optional `tracemalloc`
  delta), never asserts a leak without retention evidence.

## Example debugging sessions

**"Why did my sprite become a rectangle?"**

```
resource_trace(project=..., asset_id="assets://kenney/player_survivor_gun.png", include_preview=true)
  -> real decode status, pixel dimensions, alpha presence, or the exact provider failure
render_inspect(action="entity", project=..., entity=...)
  -> Component -> world transform -> RenderItem, via the real extract_render_frame
render_snapshot(project=..., mode="edit") and mode="runtime"
  -> real pixels, both editor and play-style rendering
diagnostics_analyze(run_id=<the snapshot's run_id>)
  -> any capture/decode failures aggregated by signature, not raw log lines
```

**"How does Godot solve this?"**

```
source_search(repos=["godot"], query="Sprite2D")
source_read(repo="godot", relative_path=..., start_line=..., end_line=...)
source_search(repos=["expra"], query=<the analogous Expra concept>)
```

Direct local source access — not a generic web explanation. Verified
live: searching Godot for `class Sprite2D` and reading the real
`scene/2d/sprite_2d.h`, then searching Expra for `class RenderItem`, both
returned real matches from the real checked-out source trees.

**"Did this change actually work?"**

```
run_checks(profile="blacksite")            # or whichever profile is relevant
render_snapshot(project=..., mode="runtime")
runtime_probe(project=..., steps=[{"action": "play"}, {"action": "key_down", "key": "w"},
                                    {"action": "tick", "dt": 0.25}, {"action": "inspect_entity", "entity": ...}])
```

Or, for the fully interactive version against the real editor:

```
editor_session(action="start")
editor_session(action="open_project", session_id=..., project=...)
editor_session(action="play", session_id=...)
editor_session(action="send_key", session_id=..., key="w", phase="down")   # real Tk event_generate
editor_session(action="wait", session_id=..., duration_ms=250)
editor_session(action="send_key", session_id=..., key="w", phase="up")
editor_session(action="capture_viewport", session_id=...)                  # real MCP ImageContent
editor_session(action="stop", session_id=...)                              # edit scene provably restored
editor_session(action="close", session_id=...)
```

Verified live end-to-end on the real Blacksite Relay project: a genuine Tk
keypress moved the real "Operative" entity by the exact amount its actual
Behaviour script computes, a real screenshot was captured mid-play, and
`stop` restored the entity's position to the exact original value.

## Answering the design spec's final questions

- **Can an agent prove which Expra source/interpreter is actually
  running?** Yes — `workspace_doctor`, verified against a real
  source-vs-configured-python mismatch check.
- **Can it read current Godot C++ directly?** Yes — `source_search` +
  `source_read`, verified against the real local Godot checkout.
- **Can it read PPB, MiniPyEngine, Ursina and original exp UI code
  directly?** Yes — same tools, same containment, all five reference
  roots confirmed real on this machine.
- **Are reference repositories guaranteed read-only?** Yes, enforced in
  code (`source_access.py`), not just by config convention.
- **Can it inspect a Scene/Entity/Component without executing game
  scripts?** Yes — `expra_inspect`/`render_inspect`/`resource_trace`,
  confirmed by reading the actual parsing code that no project Python is
  ever imported.
- **Can it trace an asset from logical ID to decoded pixels?**
  Yes — `resource_trace`, verified against a real texture
  (`assets://kenney/player_survivor_gun.png`, 51x43px, alpha present).
- **Can it inspect RenderFrame and RenderPlan?** Yes —
  `render_inspect(action="frame"|"plan"|"operation"|"captures")`, using
  the real `extract_render_frame`/`RenderPlanBuilder`.
- **Can it obtain a real renderer screenshot as MCP image content?**
  Yes — `render_snapshot` and `editor_session(action="capture_viewport")`,
  both return genuine `ImageContent`.
- **Can it operate a real Expra editor debug session?** Yes —
  `editor_session`, a real Tk `EditorWindow` driven through a dedicated
  worker process, verified against the full spec acceptance scenario.
- **Can it send keyboard input and verify entity movement?** Yes, through
  the REAL Tk event binding path (`event_generate`), not direct
  `InputMap` injection — verified: the real "Operative" entity moved by
  the exact amount its actual Behaviour script computes.
- **Can it aggregate a 500-line repeated error into one structured
  diagnostic?** Yes — `diagnostics_analyze`; verified against a real bug
  (Space Pong's paddles use an unsupported `rounded_rectangle` primitive),
  collapsing 2 raw failure records into 1 signature with `count=2`.
- **Can it run focused and full test suites without arbitrary shell
  access?** Yes — `run_checks`, argument arrays only, structured
  `--junitxml`/JSON parsing.
- **Can it detect source-vs-installed-package interpreter mismatches?**
  Yes — `workspace_doctor`.
- **Can it be configured easily on Linux, Windows, macOS and WSL?**
  Linux: yes, verified end-to-end. Windows/macOS/WSL: implemented per
  spec, not independently verified on this Linux-only machine.
- **Does exported Expra remain completely independent from MCP?** Yes —
  enforced by automated tests (`tests/test_decoupling.py`) that
  statically scan all of `src/expra_engine/` (including the export
  closure) for any `mcp`/`expra_dev_mcp` import, and check
  expra-engine's own `pyproject.toml` for the same.

## Known limitations / deferred

- `editor_session(action="capture_viewport")` captures the pygame-rendered
  sprite/texture layer via the real `tk.PhotoImage`, not Canvas-drawn
  overlays (grid, collider outlines, selection markers) — those are vector-
  drawn directly on the Canvas; `canvas.postscript()` captures them too but
  needs an external PS-to-PNG conversion step this project deliberately
  did not add as a new dependency.
- `render_inspect(action="frame_scene")` and
  `editor_session(action="frame_scene")` both report `available: false`:
  no frame/fit-view method exists on `EditorWindow` in this codebase
  version (confirmed by source search), not a gap in this MCP server.
- Windows/macOS/WSL support is implemented per the original design
  constraints but not independently verified — this development machine
  is Linux-only.
- No SQLite/FTS code index: ripgrep (when on PATH) or the pure-Python
  fallback (proven load-bearing on this very machine — `rg` is not
  actually on this shell's `PATH`) are fast enough for this repo's scale.
- No remote multi-user deployment, database, web dashboard, embeddings,
  arbitrary shell, source-editing tool, git commit/push tool, MCP sampling,
  agent-to-agent orchestration, or DAP implementation — all explicitly out
  of scope for local single-developer tooling, per the original design
  constraints.
