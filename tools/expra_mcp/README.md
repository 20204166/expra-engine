# expra-mcp

Local development/debugging MCP server for the `expra-engine` working tree.
Development tooling only -- **never** part of exported Expra games (see the
decoupling tests in `tests/test_decoupling.py`).

## Status: Phase 2G of 2G -- COMPLETE

All 14 tools, 1 resource template, and 4 prompts from the original design
spec are implemented and verified against real execution (not just unit
tests in isolation). See `docs/DEVELOPMENT_MCP.md` at the repo root for the
full architecture writeup, security model, client setup for all five
supported clients, platform notes, troubleshooting, and the spec's own
final-report questions answered point by point.

Implemented so far:

- Real `mcp` SDK v2 (`mcp>=2.2,<3`, currently pinned to 2.2.0) `MCPServer`
  instance, not a hand-rolled JSON-RPC lookalike.
- `stdio` transport (default) and Streamable HTTP transport
  (`127.0.0.1`-only by default, per spec).
- `workspace_doctor` -- environment/interpreter identity, whether
  `expra_engine` imports from the configured source tree, pygame/Tk
  availability, dev-tool availability, reference-repo status, and an overall
  `READY` / `READY_WITH_LIMITATIONS` / `NOT_READY` verdict. Always read-only.
- `source_search` -- literal/regex search across the six source roots
  (`expra`, `godot`, `ppb`, `minipy`, `ursina`, `exp_ui`). Uses ripgrep when
  it's on PATH; otherwise a pure-Python walker fallback -- **not defensive
  boilerplate**: `rg` is not actually on this machine's PATH (it only lives
  inside OpenCode's own cache dir), so the fallback is what real usage here
  exercises. Capped results, `truncated` reporting, default excludes
  (`.git`, `build`, `dist`, `__pycache__`, `.venv`, `node_modules`, ...).
- `source_read` -- bounded/paginated file reads (400-line cap), optional
  best-effort `symbol` lookup, git revision when the root is a checkout
  (only `expra` is, currently -- the five reference repos are plain
  extracted trees, not checkouts, and that's reported honestly as `null`).
- `repo_inspect` -- read-only git introspection of the `expra` root only
  (`status`, `diff`, `diff_stat`, `changed_files`, `branch`, `head`,
  `recent_commits`). No commit/push/checkout/reset/clean/rebase/merge.
- `source://{repo}/{path}` resource template -- read-only, path-contained,
  200KB direct-read cap with a pointer to `source_read` pagination beyond
  that.
- Path-containment enforcement (NUL bytes, absolute paths, symlink/`..`
  escape) is shared by every source tool and the resource template via
  `source_access.py`; reference roots are read-only in code regardless of
  what config claims.
- `expra-mcp init` / `doctor` / `config show` / `config validate` /
  `config emit {opencode,generic}` CLI.
- Config discovery: `--config` > `$EXPRA_MCP_CONFIG` > `./.expra-mcp.toml` >
  OS user config dir. `${ENV}` substitution and `~` expansion in TOML values.
- OpenCode client-config emitter verified against OpenCode's real installed
  schema (`opencode.json` at project root; no `protocol` field -- that was
  the spec's illustrative example, not OpenCode's actual schema).
- `expra_inspect` -- static, non-code-executing project/scene inspector
  (`project`, `scene`, `entity`, `component`, `component_schema`,
  `input_map`, `camera`; `systems`/`lifecycle` correctly report
  `available_statically=false` -- confirmed by reading `runtime/system.py`
  that there's no static system registry, and lifecycle is inherently a
  runtime concept -- rather than guessing at data that doesn't exist).
  Verified against the real `examples/blacksite_relay` project, including
  its actual "Aim Indicator" entity from the spec's own acceptance scenario.
- `render_inspect` -- traces the REAL render pipeline (Expra's actual
  `extract_render_frame` + `RenderPlanBuilder`, not a reimplementation):
  `capabilities` (a genuinely headless `PygameRenderer` -- zero
  `pygame.display` calls), `frame`, `plan`, `operation`, `captures`, `entity`
  (matches by `RenderItem.key == entity.entity_id`, confirmed from the real
  extractor source, not guessed). `cache` correctly reports
  `available_statically=false` (each static call is an isolated subprocess
  with no persistent cache to inspect -- that's Phase 2F's editor_session).
- `resource_trace` -- traces a real asset end-to-end through the actual
  `PygameResourceProvider`: logical ID -> resolved path -> content
  hash/size -> real Pygame decode -> pixel dimensions/alpha -> that
  provider's `last_failure`. `include_preview=true` returns a genuine MCP
  `ImageContent` block alongside the structured trace (verified: decoded
  the real `assets://kenney/player_survivor_gun.png`, 51x43px, alpha
  present).
- Both `expra_inspect` and `render_inspect` run via a bundled
  `_static_runner.py` script executed as a subprocess under the
  **configured Expra interpreter** -- this server's own process still never
  imports `expra_engine` (design point 6, unbroken since Phase 2A). Caught
  and fixed a real stdout-corruption bug this way: `import pygame` prints a
  community banner to stdout, which would have corrupted the runner's
  single-JSON-line contract -- fixed via `PYGAME_HIDE_SUPPORT_PROMPT=1` plus
  defensive last-line parsing on the receiving end.
- `render_snapshot` -- real pixels, not a filename. `mode="edit"` calls the
  actual `render_editor_frame_to_image` the real editor uses (same
  preflight/diagnostics, same strict all-or-nothing failure semantics);
  `mode="runtime"` calls `PygameRenderer.start()`/`.render()` directly,
  matching how a live game actually draws, and -- unlike edit mode --
  returns the surface's real partially-correct pixels even when one item
  failed, rather than discarding a still-useful image. Every call gets a
  `run_id`, writes the PNG under the configured artifact directory with its
  sha256, and returns a genuine MCP `ImageContent` block. Caught and fixed a
  second real bug this way: the runner never called `pygame.font.init()`,
  so every text entity failed with "font not initialized" and poisoned
  whole frames -- fixed with `pygame.font.init()` before rendering.
  `compare_to_run_id` diffs against a prior run's saved artifact (same
  dimensions / different-pixel-count / difference-ratio / mean-absolute-
  difference / bounding box), computed via direct pixel access in the same
  Expra-interpreter subprocess -- no new image-library dependency needed.
- `diagnostics_analyze` -- aggregates a `render_snapshot` run's captured log
  records by `(logger, level, message_template)` signature into
  count/first/last/sample entries. Built as its own aggregation layer
  rather than wrapping `RenderDiagnostics` directly, after confirming by
  reading its full source that it only dedups live, in-process repeats and
  tracks no counts or timestamps at all. Verified against a real bug, not a
  fixture: Space Pong's paddles use `PrimitiveComponent(kind=
  "rounded_rectangle")`, which the real `PygameRenderer` does not support --
  2 raw failure records (left + right paddle) correctly collapse into 1
  signature with `count=2`.
- `render_inspect(action="compare_modes")` -- compares the Edit-default and
  Play-style `OrthographicCamera`, built with Expra's REAL construction
  math (confirmed by reading `rendering.py`: the camera seeds its aspect
  ratio at construction time, and `apply_dict()`'s width override
  recomputes height *preserving that seed aspect* -- so Edit-vs-Play height
  divergence is a direct, provable consequence of differing pixel-viewport
  aspect ratios, not a guess). Verified against a known-real value: feeding
  in Blacksite Relay's actual editor-panel-vs-game-window dimensions
  (320x240 vs the real hardcoded 1280x720 from `__main__.py`) reproduces
  the exact real hardcoded height, 49.5, bit-for-bit. Classifies each
  difference (`EXPECTED_EDITOR_DIFFERENCE` / `ENGINE_PARITY_BUG`); with no
  viewports supplied, says outright that the comparison isn't informative
  rather than pretending default-vs-default proves anything.
- `runtime_probe` -- drives a REAL headless `Engine` (`core/engine.py`,
  confirmed zero pygame/Tk dependency in the whole file) through a
  deterministic step sequence within one subprocess call, since scene/
  behaviour/physics state must persist across steps: `play`, `pause`,
  `resume`, `stop`, `tick(dt)`, `key_down`/`key_up` (real semantic input via
  `InputMap.press()/.release()` and the real Engine event queue -- never
  direct injection), `inspect_entity`, `inspect_render`, `raycast`,
  `overlap`. **This is the one tool that genuinely executes project-
  authored Python** -- confirmed by reading `runtime/script_registry.py`:
  `ScriptRegistry._load()` does a real
  `importlib.util.spec_from_file_location` + `exec_module` on the project's
  own Behaviour script the moment `engine.play()` runs (gated behind first
  touching the lazy `engine.behaviour_system` property, or it silently
  never happens -- a real gotcha caught by reading the source, not
  guessed). Verified against real, not scripted, behavior: simulating a
  0.25s "w" keypress on Blacksite Relay's "Operative" entity moves it
  exactly as its actual `blacksite_relay_behaviour.py` script computes,
  with different real speeds for different directions. Gated to
  `workspace.trusted_project_roots` (default: exactly `examples/`, the
  only real project directories in this repo) -- refuses anything else.
  One failing step reports `ok=false` and does not abort the rest of the
  sequence.
- `run_checks` -- named profiles only, never an arbitrary shell: pytest
  profiles (`renderer`, `blacksite`, `space_pong`, `neon_arena`, `physics`,
  `resources`, `backbuffer`, `editor_texture`, `export`, `full`,
  `full_xvfb`, `focused`) parse real `--junitxml` output into
  collected/passed/failed/skipped + bounded failure summaries; `ruff`
  (`--output-format json`), `pyright` (`--outputjson`), and `mypy` parse
  each tool's own structured output; `compileall`, `diff_check` (via the
  same `git_utils.run_git` `repo_inspect` already used), and `build_wheel`
  round out the set. Full output always goes to a log file
  (`log_path`), never dumped inline. Verified against this repo's real
  state, not fixtures: `ruff` found 62 real lint violations and `mypy`
  found 32 real type errors already present in expra-engine's own source
  (reported accurately, not "fixed" -- that's out of scope for this tool).
- `export_inspect` -- drives the REAL exporter
  (`export/exporter.py`'s `GameExporter`, `export/plan.py`'s `ExportPlan`,
  `export/verify.py`'s `verify_export` + forbidden-import scanner).
  Discovered mid-implementation that a real export is much heavier than
  "inspection" -- `GameExporter.export()` actually installs a Python
  runtime and downloads packages over the network -- so `action="export"`
  is refused outright unless `execution.allow_network=true` is set,
  pointing the caller at `action="plan"` (validates an `ExportPlan`'s
  configuration without running anything) instead. `action="verify"` runs
  the real verification + forbidden-import scan against an existing build
  directory, read-only, no gating needed. `plan`/`export` are gated to
  `trusted_project_roots`, same as `runtime_probe`.
- `editor_session` -- operates a REAL Tk `EditorWindow` (not simulated)
  through a long-lived worker subprocess (`_editor_worker.py`) and a
  newline-delimited JSON IPC protocol, per spec: an internal reader thread
  only touches stdin/a queue, never Tk; all Tk mutation happens on the
  worker's own main thread inside `root.after()`-scheduled polling, exactly
  matching `ui/editor_window.py`'s own documented threading invariant.
  `open_project` mirrors the real `ProjectWorkflow.open_loaded()` sequence
  exactly (down to the easy-to-miss `engine.set_script_registry(...)` call
  real File > Open Project makes). `play`/`pause`/`resume`/`stop` call the
  real `_act_play`/`_act_pause`/`_act_stop` handlers a human clicking those
  buttons would trigger. **`send_key` deliberately uses genuine Tk
  `event_generate`**, not direct `InputMap` injection, per the spec's own
  instruction not to treat bypassing the UI as proof of editor keyboard
  handling -- and this caught a real bug during implementation: synthetic
  Tk key events are silently dropped unless the window actually has
  keyboard focus, which nothing gives it in an unattended worker; fixed
  with an explicit `root.focus_force()`. A second real bug: `select_entity`
  initially forwarded a bare name straight to `_on_hierarchy_select()`,
  which only does exact `entity_id` lookup (confirmed by reading it) --
  silently mis-selecting nothing while reporting a bogus `selected_id`;
  fixed to resolve name-or-id first, matching every other entity-taking
  action. `capture_viewport` pulls a real PNG directly from the live
  `ViewportPanel`'s `tk.PhotoImage` (`.write(path, format="png")`, zero new
  dependencies) -- documented honestly as the pygame-rendered layer only,
  not Canvas-drawn overlays (grid/collider outlines/selection markers).
  Verified end-to-end against the spec's own acceptance scenario on the
  real editor: open Blacksite -> Play -> genuine Tk keypress for "w" ->
  wait -> the real "Operative" entity moved by exactly the same amount
  Phase 2E's headless `runtime_probe` produced -> screenshot -> select ->
  Stop -> the edit scene's position is restored to the exact original
  value, bit-for-bit.
  For headless/CI use, **manages its own `Xvfb :N` process directly rather
  than shelling out to `xvfb-run`** -- discovered mid-implementation that
  `/usr/bin/xvfb-run` runs the wrapped command as `"$@" 2>&1`, merging
  stderr into stdout, which would silently corrupt this protocol's
  newline-delimited JSON contract the moment expra_engine logged anything;
  verified both the native-display and self-managed-Xvfb paths end-to-end,
  with proper cleanup of both the worker and the Xvfb process on close.
  Reports `editor_session_available=false` with a clear reason (never a
  confusing hang or crash) when no usable display exists.

Phase 2G additions:

- `performance_probe` -- distinguishes a bounded retry/log flood from an
  actual retained-resource leak with real measurements, never a guess.
  `render_stress`/`resource_cache` (static, headless) and
  `editor_redraw_stress` (against a real live Tk session) all report
  `bounded` / `growing` / `inconclusive` backed by real before/after
  numbers (resource cache size, logger handler count, Canvas item count,
  real Tcl `image names` count for PhotoImage references, optional
  `tracemalloc` delta). **Found and fixed a real measurement bug twice**
  (once in the static runner, once independently in the editor worker):
  both "before" counts were measured *after* attaching this tool's own
  temporary log-capture handler, so a perfectly healthy render loop
  reported a spurious handler "leak" of exactly 1 -- and a healthy
  multi-texture scene's cache growth was misclassified `inconclusive`
  instead of `bounded` until the verdict heuristic was corrected to
  compare against the scene's real distinct-texture count rather than a
  fixed constant. Live-verified afterward: `render_stress` against
  Blacksite Relay reports `bounded` with symmetric before/after handler
  counts; `editor_redraw_stress` against a real editor session reports
  Canvas item count and PhotoImage count both perfectly stable (135->135,
  27->27) across 15 real redraws.
- Four real MCP prompts (`debug-renderer`, `mine-reference`,
  `tk-regression`, `release-check`) via the SDK's native prompt primitive
  (`prompts/list`/`prompts/get`), not a custom "prompt tool" workaround --
  each references this server's own real tool names in the right order,
  not the original spec's generic step descriptions.
- VS Code, Cursor, Claude Code, and Codex client-config emitters, each
  verified against that client's real current documentation (not the
  original spec's illustrative examples) via live doc lookups at
  implementation time: VS Code's workspace key is `servers` (not
  `mcpServers`); Cursor's is `mcpServers`; Claude Code's CLI requires a
  literal `--` separator between its own flags and the server command;
  Codex's TOML block uses `args` as an array plus a nested
  `[mcp_servers.NAME.env]` table.
- `docs/DEVELOPMENT_MCP.md` at the repo root: full architecture, security
  model, all five clients' setup, platform notes, troubleshooting, and the
  original design spec's closing questions answered individually against
  what was actually verified versus what's implemented-but-unverified on
  this Linux-only development machine.

## Setup

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

`init` writes `./.expra-mcp.toml` (gitignored -- machine-local paths) and
immediately runs `doctor` against it.

## Running

```bash
.venv/bin/expra-mcp serve --transport stdio          # default
.venv/bin/expra-mcp serve --transport http --port 8000
```

## OpenCode

```bash
.venv/bin/expra-mcp config emit opencode --write   # writes ./opencode.json
opencode mcp list                                   # should show "expra connected"
```

## Tests

```bash
.venv/bin/pytest tests/ -v
```

`tests/test_protocol_spine.py` drives the server exclusively through the
official `mcp` SDK `Client` -- in-process, over a real `stdio` child process,
and over a real Streamable HTTP connection -- never by calling server-internal
functions directly. `tests/test_decoupling.py` proves nothing under
`src/expra_engine` imports `mcp` or `expra_dev_mcp`.
