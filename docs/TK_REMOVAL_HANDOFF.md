# Tk / ttkbootstrap removal: handoff

Repo: `/home/btn17/Downloads/expra-engine` (baseline HEAD `b03ff95`, large uncommitted working tree).
Game repo (do not modify): `/home/btn17/Downloads/the-second-mark`.

> **Historical handoff snapshot.** The TODO list below records the remaining
> work at handoff time. See “Continuation result” at the end for its disposition
> and current verification; do not treat the old TODO list as active.

## Standing rules from the user
- DO NOT commit, DO NOT push.
- No `git stash`, `git reset --hard`, `git clean`, or repo-wide `ruff --fix` (run ruff only on explicit file lists).
- Do not touch unrelated code: renderer behaviour, physics, combat, document codecs/schemas, runtime, save system.
- Never unlock or inject input into a locked desktop.
- Shared editor logic (`*_core`, `hierarchy_rows`, `dialog_provider`, `viewport_core`, etc.) must be preserved. Only Tk presentation and dual-frontend plumbing is removed.
- Export blocklists for tkinter/ttkbootstrap/PySide6 stay (exported games must not contain any GUI toolkit).
- One mishap: `git rm --cached -r .` was run once on `src/expra_engine` and immediately repaired with `git restore --staged src/expra_engine`. The index should have nothing staged (`git diff --cached` empty). Verify.

## DONE (source)
- Deleted: `ui/{editor_window,hierarchy,inspector,asset_browser,console,toolbar,viewport,timer_delivery,layout}.py`, `editor/{app,export_dialog,delivery,runtime_preview}.py`, `tools/perf/bench_pixel_bridge*.py`.
- `main.py`: Qt-only, no `--ui` flag, no `DEFAULT_UI`.
- `editor/qt/preflight.py`: Tk fallback text removed.
- `dialog_provider.py`: `TkDialogProvider` removed. The `DialogProvider` protocol is kept because tests use fakes and it separates the workflow from dialog presentation.
- `ProjectWorkflow` and `ProjectProcessController` use `window._dialogs`.
- `ui/normal_map_preview.py`: Tk `show_...` removed; the preview model is kept.
- `normal_map_actions.py`: mixin no longer has a default present method.
- `ui/editor_pixel_renderer.py`:
  - `PillowEditorPhotoImage` removed.
  - `render_editor_frame_to_tk_image` renamed to `render_editor_frame_to_pixel_image`.
  - `image_master` removed.
  - `image_factory` is now REQUIRED for `EditorPixelRenderer` and `ViewportCore._init_viewport`.
  - `QtEditorImage(image)` no longer takes `master`.
- `runtime/texture_diagnostics.py`: `image_master` replaced by `editor_image_factory`.
- `ui/styles.py`: `configure_app_styles`, fonts, SPACING, CONTROL and most STYLE_* removed. Kept: COLORS, accent themes, `editor_entity_kind`, the three toolbar STYLE_* constants, and `toolbar_style_for_role`.
- `button_coordinator`: no tkinter probe (widget errors are `RuntimeError`).
- Window core and Qt shell:
  - `_cancel_shell_timers` and `_sash_after_id` removed.
  - `WindowGeometry.from_tk_geometry/to_tk_geometry` renamed `from_geometry_string/to_geometry_string`. The persisted string format is unchanged.
  - `tk_keysym`/`tk_state` renamed `keysym_name`/`modifier_state`.
  - `qt_shortcut_from_tk` renamed `qt_shortcut_from_sequence`.
  - The "TkDefaultFont" sentinel is now "default-font".
- `_release.py` required-member and surface lists now point at the `editor/qt/*` files.
- `pyproject.toml`: `ttkbootstrap` dependency removed; PySide6 stays.
- Docstrings and comments cleaned across `editor/`, `editor/qt/`, `export/`, `core/`, `design/`, `coordinators/`.
- KEPT ON PURPOSE (report as debt): `QtCanvas` (Tk-Canvas-shaped API), `QtTreeAdapter` (Treeview-shaped, used by `reconcile_treeview`) and `field_vars`. `ViewportCore`, the inspector and the asset browser depend on these surfaces, and rewriting them would be a large redesign. Event sequences such as `"<Button-1>"` are the canvas API's string vocabulary.
- All `expra_engine.*` modules import, and neither tkinter nor ttkbootstrap loads. Check: import every module except `__main__` (importing it launches the editor).

## DONE (MCP, `tools/expra_mcp`)
- `_editor_worker.py`: `_TkShell`, `_make_shell` and `EXPRA_EDITOR_UI` removed; the handshake still reports `"ui":"qt"`.
- `workspace_doctor` model: `tk: TkIdentity` replaced by `qt: QtIdentity(available, pyside6_version, ...)` (adapter, models, server text).
- Prompt `tk-regression` renamed `editor-regression` (server and `tests/test_prompts.py`).
- README, server and session docs updated.

## DONE (tests)
- Support: `tests/support/{tk_display,editor_frontends}.py` removed. New `tests/support/qt_editor.py` (`QtEditorHarness`, `make_editor`, `pump`). `tests/conftest.py` patches the Qt window's default preferences path for every test and provides the `frontend` and `window` fixtures. `TimerMaster` and similar fakes removed from `scheduling.py`.
- Replaced (parity tests converted to Qt-only, valuable assertions kept):
  - `test_editor_window_behaviour.py`
  - `test_editor_document_roundtrip.py` (save/reopen and editor bytes == codec bytes)
  - `test_editor_pixel_bridge.py`
  - `test_export_dialog_qt.py`
  - `test_gui_boundaries.py` (adds "no module imports tk")
  - `test_qt_panels.py`
  - `test_qt_viewport.py` (golden item streams)
  - `test_mcp_editor_worker.py`
  - `test_second_mark_editor_acceptance.py`
  - `test_qt_timer_delivery.py`
- Deleted: `test_bench_pixel_bridge`, `test_editor_app`, `test_delivery_queue` (its unique contracts were ported into `test_qt_delivery_queue.py`), `test_timer_delivery`.
- Edited to Qt or shared core: `test_main`, `test_qt_packaging`, `test_dialog_provider`, `test_export_dialog`, `test_editor_frontend_state_sync`, `test_release`, `test_world_hierarchy`, `test_world_viewport`, `test_scale_performance`, `test_editor_render_targets`, `test_editor_lighting_preview`, `test_editor_window_autosave`, `test_editor_window_viewport_camera_debounce`, `test_editor_world_workflow`, `test_multi_level_workflow`, `test_composition_workflow`, `test_blacksite_level2_dogfood`, `test_blacksite_level3_build`, `test_observability_wiring`, `test_pygame_lighting`, `test_texture_diagnostics`, `test_button_coordinator`, `test_design_tokens`, `test_viewport_transform`, `test_animated_sprite_end_to_end`.
- All of the above were run and pass.

## TODO (in order)
1. Finish the remaining Tk-dependent tests. Run `python3 -m pytest tests --co -q` to find collection errors.
   - `tests/test_editor_ui.py` (~1960 lines). It has Tk RuntimePreviewLoop tests (`editor.runtime_preview` is deleted; Qt has `QtRuntimePreviewLoop`), Tk panel tests and Tk EditorWindow layout and selection tests.
     - Port the logic tests to `make_editor`/`pump` (`tests/support/qt_editor.py`). Cover in the Qt window: sidebar sizing, add/duplicate/delete/undo presenting panels once, multi-select, world startup diagnostics, entity mutations blocked while playing.
     - Delete the Tk-only ones: ttk styles, sash, canvas callback-command leaks via `tk.call`, `tree.exists` per-id counters. Panel behaviour is already covered by `test_qt_panels.py`.
     - `test_inspector_value_conversion_...` is pure logic; keep it.
   - `tests/test_editor_texture_rendering.py`. It imports the removed `PillowEditorPhotoImage`, `render_editor_frame_to_tk_image`, `ui.editor_window` and `ui.viewport`, and constructs `EditorPixelRenderer` without a factory.
     - Rename to `render_editor_frame_to_pixel_image` and pass `image_factory=QtEditorImage`.
     - Drop the Tk photo-image tests (~lines 1040-1160).
   - `tests/test_editor_contributions.py`: check its Tk usage (`grep -n "tkinter\|ttk\|nametowidget\|EditorWindow"`).
2. Run the full suite: `python3 -m pytest tests/ -q`. Baseline before this pass was 2731 passed; the expected count is lower after the Tk-only tests were removed. Fix regressions. Ruff only on explicit changed files (`python3 -m ruff check <files>`).
3. MCP suite: `cd tools/expra_mcp`, use its `.venv` or the scratch `mcpvenv` (system site packages plus mcp, PySide6, python-xlib). Use `env -u DISPLAY` for the xvfb mode. Baseline 109 tests, 11 of them editor-session. Also update any test that reads the `workspace_doctor` `tk` field (none found so far).
4. Docs:
   - Update: `README.md`, `docs/ARCHITECTURE.md`, `docs/guide/{ARCHITECTURE,EDITOR,EXPORT,TROUBLESHOOTING}.md`, `docs/THREADING.md`, `tools/expra_mcp/README.md` (re-check).
   - Add a historical banner to: `PERFORMANCE_AUDIT.md`, `docs/PERFORMANCE_BASELINE.md`, `docs/CROSS_OWNER_FINDINGS.md`, `docs/URSINA_INTEGRATION_MAP.md`, `docs/GAME_*_FUTURE.md`.
   - Remove mentions of `--ui tk`, ttkbootstrap and frontend choice.
   - Check `scripts/install-common.sh` and `scripts/smoke-installed-editor.sh` for stale Tk or `--ui` text. A grep earlier found none, but re-check.
5. Search for residue: `grep -rniE "tkinter|ttkbootstrap|ImageTk|TkDialogProvider|EXPRA_EDITOR_UI|--ui|\bTk\b" --include=* src tests tools scripts docs README.md pyproject.toml`, excluding `.venv`, `build`, `dist` and `venv`.
   - Allowed: export blocklists and their tests (`export/{packager,manifest,verify}.py`, `test_export_*`), `test_gui_boundaries.py`, `test_qt_packaging.py`, `test_main.py`, and `test_runtime_ui.py:130`.
   - Everything else needs justification or removal.
6. Pyright on shared editor logic, `editor/qt`, `main.py`, `preflight.py`, the MCP worker and the packaging code. Baseline was 0 errors on the new migration code.
7. Build a wheel (`scripts/build-wheel.sh`), install it in a fresh venv, confirm PySide6 installs and `expra-editor` launches Qt, and that `--ui` is rejected. Verify wheel metadata has no ttkbootstrap. Re-run the export-leak tests (`test_gui_boundaries`, `test_export_*`, `test_qt_packaging`).
8. Acceptance on `the-second-mark`: `test_second_mark_editor_acceptance.py` passes on a copy. A physical-desktop run needs the user's unlocked desktop (real X11 harness in the scratchpad `phys/`). Only do it if the desktop is unlocked. Otherwise report it as offscreen-only.
9. Failure recovery: Play runtime error, Run Project failure, missing project, bad document, close while a worker is active, MCP worker close, export failure. The existing tests (`test_qt_delivery_stress.py`, project workflow tests, MCP tests) cover most of these; confirm they still pass.
10. Final report in the format the user requested (33 items). Remaining debt to state: the Tk-shaped Qt adapters (canvas, tree, field vars), the `_root` attribute name on the window, the `photoimage_*` JSON keys kept for protocol compatibility, and the AppCoordinator threading redesign (explicitly out of scope).

## Useful facts
- Offscreen tests: `QT_QPA_PLATFORM=offscreen` (set by `tests/support/qt_app.py`).
- Qt `EditorWindow` is `editor/qt/main_window.py`. `_root` is the window itself.
- `window._hierarchy._tree` is a `QtTreeAdapter`; its raw widget is `.widget` and its item map is `_items`.
- Real mouse events on tree rows can be sent with `QTest`; see `_mouse_click` in `test_composition_workflow.py`.
- Watch out: a `sed` such as `window._root.update()` -> `pump(window)` also matches variables ending in `window` (for example `reopened_window`). Check the variable name.
- Do not use `pkgutil.walk_packages` without skipping `__main__`.
- Commands taking more than about 10 s get auto-backgrounded; read the output file listed in the notification.

## Continuation result — 2026-09-29

The outstanding Tk-removal cleanup, Qt-only test migration, documentation
updates, and requested verification were completed without committing. The
following supersedes the handoff-time TODO list above:

- Removed the remaining Tk-only `test_editor_ui.py` suite and the obsolete
  `test_editor_texture_rendering.py` suite; retained inspector value
  conversion/formatting assertions in `test_inspector_core.py`. Qt panel,
  viewport, pixel-image, and image-bridge behavior remains covered by the
  replacement suites.
- Converted the old World frontend parity test to a Qt-only integration test
  (`test_world_qt_editor.py`); fixed Qt key-input tests to use the shared Qt
  harness; removed obsolete `--ui tk` preflight expectations.
- MCP `open_project` now delegates to the canonical
  `ProjectWorkflow.open_loaded()` path. This also handles World entrypoints;
  a real worker regression proves World opens with `document_kind="world"` and
  `entity_count=0`.
- `scripts/build-wheel.sh` now removes stale setuptools `build/` output before
  building. A regression test covers cleanup ordering. This fixed a real stale
  wheel containing removed Tk modules when an old `build/lib` was present.
- Current full verification: engine suite **2541 passed, 2 warnings, 290
  subtests**; full MCP suite **109 passed**, including editor sessions **11
  passed**; export profile **129 passed**; focused Pyright over shared editor,
  Qt frontend, startup, release, and MCP worker **0 errors**; relevant-file
  Ruff and `git diff --check` passed.
- Broad repository Pyright is not clean: it reports **639 errors** in other
  current-tree areas. The scoped Qt/shared-editor/MCP check above is clean.
- `scripts/build-wheel.sh` built and verified
  `expra_engine-0.6.1.0-py3-none-any.whl` (224 members). A fresh venv install
  installed PySide6 6.11.2 as a normal dependency; `expra-editor` stayed in the
  Qt event loop under an offscreen 5-second smoke, `--ui tk` was rejected, and
  importing the installed entrypoint loaded no Tk modules. Export verification
  passed and the wheel no longer contains the removed legacy editor modules.
- The Second Mark acceptance test passed as part of the full engine suite using
  a temporary project copy and offscreen Qt. No physical desktop interaction
  was performed.
- Project/Scene/Level/World codecs and formats were not changed by this
  continuation. Pygame/game runtime source was not changed by this continuation.

Remaining migration debt is intentional: `QtCanvas`, `QtTreeAdapter`,
`field_vars`, the window `_root` alias, and the legacy `photoimage_*`
observability target names retained for MCP compatibility. Core/runtime/export
remain GUI-toolkit independent; export blocklists still explicitly reject Tk,
ttkbootstrap, and Qt dependencies.

## Consolidation audit — 2026-09-29

A follow-up consolidation pass removed the last Tk-shaped editor seams that
survived the removal pass, and one pre-existing test race it exposed:

- **Viewport geometry/scheduling** — `ViewportCore`, world authoring, and asset
  drop no longer call `winfo_width/height/rootx/rooty` or `after_idle`. The
  shared viewport now uses `viewport_size()`/`global_origin()` and
  `schedule_idle()`; `QtCanvas` supplies those semantic methods and no longer
  exposes `winfo_exists`, `configure`, or `focus_set`. (`test_qt_viewport.py`
  pins this.)
- **ButtonCoordinator** — dropped the duck-typed `config`/`winfo_exists` widget
  contract for a semantic `ActionWidget` protocol (`bind_action`, `set_enabled`,
  `is_valid`); `QtActionWidget` implements it.
- **Menus** — removed `MenuFactory`/`QtMenu` indirection. The Qt window builds
  native `QMenu` actions directly and the `QKeySequence` handling is owned by
  Qt. `ShortcutRegistry.bind_all` (dead Tk-era API) was removed; shortcuts now
  use Qt `QKeySequence` syntax (`Ctrl+Z`, `Ctrl+Shift+S`) throughout, with the
  legacy `<Control-z>` form rejected. `qt_shortcut_from_sequence` was removed.
- **Tree reconciliation** — `reconcile_treeview` renamed `reconcile_tree_rows`
  and documented against a retained-tree contract rather than Tk `Treeview`.
- **EditorContext** — dropped the unused `root` field.
- **Test race fixed** — `test_dropping_a_level_asset_on_the_world_viewport_adds_it_at_the_drop_point`
  computed its expected world origin after the drop re-rendered (and re-framed)
  the world, so it intermittently failed. It now captures the expected origin
  from the pre-drop camera.

Verification after the consolidation audit: engine suite **2540 passed, 2
warnings, 288 subtests**; scoped Pyright over shared editor/Qt/coordinator code
**0 errors**; ruff and `git diff --check` clean.
