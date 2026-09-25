"""Builds the expra-mcp ``MCPServer`` instance and registers its tool surface.

Phase 2A registered ``workspace_doctor`` (the protocol-compliance spike).
Phase 2B added the source/reference layer: ``source_search``, ``source_read``,
``repo_inspect``, and the ``source://{repo}/{path}`` resource template.
Phase 2C added static Expra inspection: ``expra_inspect``, ``resource_trace``,
and ``render_inspect`` (static-only actions -- no live GUI yet, that's 2F).
Phase 2D added renderer/image evidence: ``render_snapshot`` (real pixels via
the actual PygameRenderer/EditorPixelRenderer draw path), ``diagnostics_analyze``
(signature aggregation over a snapshot's captured log records), and
``render_inspect(action="compare_modes")`` (Edit-vs-Play camera parity).
Phase 2E adds execution: ``runtime_probe`` (a real headless Engine driven
step-by-step -- the one tool that genuinely executes project-authored
Behaviour code, gated by trusted_project_roots), ``run_checks`` (named
pytest/ruff/pyright/mypy/build profiles, never an arbitrary shell), and
``export_inspect`` (the real exporter -- ``action="export"`` gated behind
``execution.allow_network`` since it downloads a Python runtime + packages).
Phase 2F adds ``editor_session``: a REAL Tk ``EditorWindow`` driven through
a long-lived worker subprocess and a newline-delimited JSON IPC protocol
(``_editor_worker.py`` / ``editor_sessions.py``), never touching Tk from
this server's own process/thread. Performance/polish lands in 2G (see
tools/expra_mcp/README.md).
"""

from __future__ import annotations

import base64
import shutil
from typing import Any, Literal

import mcp.types as types
from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.types import ToolAnnotations

from . import (
    _version,
    artifacts,
    diagnostics,
    project_trust,
    repo_inspect,
    run_checks,
    source_access,
)
from .config import ExpraMcpConfig
from .editor_sessions import EditorSessionError, EditorSessionManager
from .expra_adapter import gather_workspace_doctor, resolve_configured_python
from .expra_static import StaticInspectionError, run_static_op
from .git_utils import git_identity
from .models import (
    ActionInspectResult,
    CheckResult,
    DiagnosticsAnalyzeResult,
    EditorSessionResult,
    ExportInspectResult,
    GitFileChange,
    PerformanceProbeResult,
    RenderSnapshotResult,
    RepoInspectResult,
    ResourceTraceResult,
    RuntimeProbeResult,
    RuntimeStepResult,
    SourceMatch,
    SourceReadResult,
    SourceSearchResult,
    WorkspaceDoctorResult,
)
from .repo_inspect import RepoInspectError
from .run_checks import RunChecksError
from .source_access import SourceAccessError
from .source_read import read_source
from .source_search import search_root

SERVER_NAME = "expra"

MAX_SEARCH_RESULTS_CAP = 100
MAX_RESOURCE_READ_BYTES = 200 * 1024

_ACTION_RESULT_TOP_LEVEL_KEYS = {"action", "executed_project_code", "available_statically", "note"}


def _to_action_result(raw: dict[str, Any]) -> ActionInspectResult:
    data = {k: v for k, v in raw.items() if k not in _ACTION_RESULT_TOP_LEVEL_KEYS}
    return ActionInspectResult(
        action=raw["action"],
        executed_project_code=raw.get("executed_project_code", False),
        available_statically=raw.get("available_statically", True),
        note=raw.get("note"),
        data=data,
    )


def build_server(cfg: ExpraMcpConfig) -> MCPServer:
    server: MCPServer = MCPServer(
        SERVER_NAME,
        title="Expra Development MCP Server",
        description=(
            "Local development/debugging bridge for the expra-engine working tree: "
            "environment identity, reference-source mining, renderer/resource evidence, "
            "and controlled test/editor execution. Development tooling only -- never part "
            "of exported Expra games."
        ),
        instructions=(
            "Call workspace_doctor before any environment-sensitive debugging. Current "
            "expra-engine source is authoritative for Expra; the reference engines (godot, "
            "ppb, minipy, ursina, exp_ui) are capability references, not templates to copy "
            "verbatim -- read the actual implementation around any source-search match "
            "before adapting it with source_read. Never modify reference source trees "
            "(they are enforced read-only). Prefer render_snapshot evidence over assuming "
            "visual success. Do not call something a memory leak without retention evidence."
        ),
        version=_version.__version__,
    )

    editor_sessions = EditorSessionManager(cfg, lambda: resolve_configured_python(cfg))

    @server.tool(
        name="workspace_doctor",
        description=(
            "Report the MCP server's and Expra's Python/interpreter identity, whether "
            "expra_engine imports from the configured source tree (vs. a stale installed "
            "package), pygame/Tk availability, dev-tool availability (git, rg, pytest, ruff, "
            "pyright, mypy, xvfb-run), default-project and reference-repository status, and "
            "an overall READY / READY_WITH_LIMITATIONS / NOT_READY readiness verdict. "
            "Always read-only; call this before any environment-sensitive debugging."
        ),
        annotations=ToolAnnotations(
            title="Workspace Doctor",
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def workspace_doctor() -> WorkspaceDoctorResult:
        return await gather_workspace_doctor(cfg, server_name=SERVER_NAME, server_version=_version.__version__)

    @server.tool(
        name="source_search",
        description=(
            "Search one or more of the six source roots (expra, godot, ppb, minipy, ursina, "
            "exp_ui) for literal text or a regex. Uses ripgrep when it's on PATH, otherwise a "
            "pure-Python fallback -- never assume ripgrep is available. Results are capped at "
            "100 and report truncated=true when more exist; refine path_globs/exclude_globs or "
            "narrow repos and call again rather than expecting a full dump. Each match includes "
            "surrounding context lines -- follow up with source_read on the exact "
            "repo/relative_path/line range to see the real implementation, never stop at the "
            "one-line match."
        ),
        annotations=ToolAnnotations(
            title="Source Search",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def source_search(
        repos: list[str],
        query: str,
        mode: Literal["literal", "regex"] = "literal",
        path_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        context_lines: int = 2,
        max_results: int = 50,
    ) -> SourceSearchResult:
        capped_max = max(0, min(max_results, MAX_SEARCH_RESULTS_CAP))
        backend = "ripgrep" if shutil.which("rg") else "pure_python"
        all_matches: list[SourceMatch] = []
        truncated = False

        for repo_id in repos:
            try:
                root = source_access.get_root(cfg, repo_id)
            except SourceAccessError as exc:
                raise ValueError(str(exc)) from exc

            remaining = capped_max - len(all_matches)
            if remaining <= 0:
                truncated = True
                break

            matches, repo_truncated = await search_root(
                root,
                query=query,
                mode=mode,
                path_globs=path_globs,
                exclude_globs=exclude_globs,
                context_lines=context_lines,
                max_results=remaining,
            )
            truncated = truncated or repo_truncated
            all_matches.extend(
                SourceMatch(
                    repository=m.repository,
                    relative_path=m.relative_path,
                    line_number=m.line_number,
                    match=m.match,
                    context=m.context,
                    context_start_line=m.context_start_line,
                    language=source_access.guess_language(m.relative_path),
                )
                for m in matches
            )

        return SourceSearchResult(
            query=query,
            mode=mode,
            repos_searched=repos,
            matches=all_matches,
            truncated=truncated,
            backend=backend,
        )

    @server.tool(
        name="source_read",
        description=(
            "Read a bounded, line-numbered window from a file in one of the six source roots. "
            "Pass start_line/end_line (from a source_search hit) for an exact range, or a best-"
            "effort symbol name to jump to its first mention. Output is capped at 400 lines per "
            "call (truncated=true if the requested window was larger) -- never dumps a whole "
            "large file; page through it with successive calls instead."
        ),
        annotations=ToolAnnotations(
            title="Source Read",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def source_read(
        repo: str,
        relative_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        symbol: str | None = None,
        context_before: int = 0,
        context_after: int = 0,
    ) -> SourceReadResult:
        try:
            root = source_access.get_root(cfg, repo)
            content, actual_start, actual_end, total_lines, truncated = read_source(
                root,
                relative_path,
                start_line=start_line,
                end_line=end_line,
                symbol=symbol,
                context_before=context_before,
                context_after=context_after,
            )
        except SourceAccessError as exc:
            raise ValueError(str(exc)) from exc

        revision = None
        if (root.path / ".git").exists():
            revision, _ = await git_identity(root.path)

        return SourceReadResult(
            repo=repo,
            path=relative_path,
            revision=revision,
            start_line=actual_start,
            end_line=actual_end,
            total_lines=total_lines,
            truncated=truncated,
            content=content,
        )

    @server.tool(
        name="repo_inspect",
        description=(
            "Read-only git introspection of the Expra working tree ONLY (never a reference "
            "repo -- none of them are even git checkouts on a typical setup). Actions: status, "
            "diff, diff_stat, changed_files, branch, head, recent_commits. No commit/push/"
            "checkout/reset/clean/rebase/merge -- this tool cannot do any of those."
        ),
        annotations=ToolAnnotations(
            title="Repo Inspect",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def repo_inspect_tool(
        action: Literal["status", "diff", "diff_stat", "changed_files", "branch", "head", "recent_commits"],
        recent_commits_count: int = 20,
    ) -> RepoInspectResult:
        repo = cfg.workspace.expra_root
        try:
            if action == "status":
                changes = await repo_inspect.status_porcelain(repo)
                current_branch = await repo_inspect.branch(repo)
                return RepoInspectResult(
                    action=action,
                    branch=current_branch,
                    dirty=bool(changes),
                    changed_files=[GitFileChange(status=s, path=p) for s, p in changes],
                )
            if action == "diff":
                return RepoInspectResult(action=action, diff=await repo_inspect.diff(repo))
            if action == "diff_stat":
                return RepoInspectResult(action=action, diff_stat=await repo_inspect.diff_stat(repo))
            if action == "changed_files":
                changes = await repo_inspect.status_porcelain(repo)
                return RepoInspectResult(action=action, changed_files=[GitFileChange(status=s, path=p) for s, p in changes])
            if action == "branch":
                return RepoInspectResult(action=action, branch=await repo_inspect.branch(repo))
            if action == "head":
                return RepoInspectResult(action=action, head_commit=await repo_inspect.head_commit(repo))
            if action == "recent_commits":
                commits = await repo_inspect.recent_commits(repo, recent_commits_count)
                return RepoInspectResult(action=action, recent_commits=commits)
        except RepoInspectError as exc:
            return RepoInspectResult(action=action, error=str(exc))

        raise ValueError(f"unknown action: {action!r}")

    @server.resource(
        "source://{repo}/{path}",
        name="source_file",
        title="Source file",
        description=(
            "Read-only access to a file inside one of the six source roots (expra, godot, ppb, "
            "minipy, ursina, exp_ui). Files over 200KB are truncated to their first 200 lines "
            "with a pointer to source_read for pagination -- never writes anything."
        ),
        mime_type="text/plain",
    )
    async def read_source_resource(repo: str, path: str) -> str:
        try:
            root = source_access.get_root(cfg, repo)
            resolved = source_access.resolve_relative_path(root, path)
        except SourceAccessError as exc:
            raise ValueError(str(exc)) from exc

        if not resolved.is_file():
            raise ValueError(f"not a file: source://{repo}/{path}")
        if source_access.is_probably_binary(resolved):
            raise ValueError(f"refusing to serve binary file as a resource: source://{repo}/{path}")

        size = resolved.stat().st_size
        text = resolved.read_text(encoding="utf-8", errors="replace")
        if size <= MAX_RESOURCE_READ_BYTES:
            return text

        preview = "\n".join(text.splitlines()[:200])
        return (
            f"[truncated: {size} bytes exceeds the {MAX_RESOURCE_READ_BYTES}-byte resource read "
            f"cap; showing the first 200 lines]\n"
            f"Use the source_read tool with repo={repo!r}, relative_path={path!r} and an explicit "
            f"start_line/end_line range to page through the rest.\n\n{preview}"
        )

    @server.tool(
        name="expra_inspect",
        description=(
            "Domain-specific static inspector for an Expra project/scene, action-dispatched: "
            "project, scene, entity, component, component_schema, systems, input_map, camera, "
            "lifecycle. NEVER executes project-authored Python -- confirmed by reading the real "
            "source: Project.load/Scene.from_dict/Entity.from_dict are pure JSON parsing, and "
            "the 'script' component type only stores script_id/behaviour_class as data, never "
            "imports the module -- so every result reports executed_project_code=false. "
            "'systems' and 'lifecycle' have no static data and report "
            "available_statically=false, pointing to runtime_probe/editor_session (later "
            "phases) instead of guessing."
        ),
        annotations=ToolAnnotations(
            title="Expra Inspect",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def expra_inspect(
        action: Literal[
            "project",
            "scene",
            "entity",
            "component",
            "component_schema",
            "systems",
            "input_map",
            "camera",
            "lifecycle",
        ],
        project: str | None = None,
        scene: str | None = None,
        entity: str | None = None,
        component_type: str | None = None,
    ) -> ActionInspectResult:
        if action in {"project", "scene", "entity", "component", "input_map", "camera"} and not project:
            raise ValueError(f"action={action!r} requires 'project' (e.g. 'examples/blacksite_relay')")
        if action in {"entity", "component"} and not entity:
            raise ValueError(f"action={action!r} requires 'entity' (an entity_id or entity name)")
        if action == "component" and not component_type:
            raise ValueError("action='component' requires 'component_type' (e.g. 'primitive', 'sprite')")

        executable, _ = resolve_configured_python(cfg)
        request: dict[str, Any] = {"op": "expra_inspect", "action": action}
        if project:
            request["project"] = project
        if scene:
            request["scene"] = scene
        if entity:
            request["entity"] = entity
        if component_type:
            request["component_type"] = component_type

        try:
            raw = await run_static_op(executable, cfg.workspace.expra_root, request)
        except StaticInspectionError as exc:
            raise ValueError(f"{exc.kind}: {exc}") from exc

        return _to_action_result(raw)

    @server.tool(
        name="render_inspect",
        description=(
            "Trace the render pipeline statically using Expra's REAL extract_render_frame and "
            "RenderPlanBuilder -- not a reimplementation. entity -> world transform -> "
            "RenderItem -> RenderFrame -> RenderPlan operation -> declared backend capability. "
            "Actions: capabilities (project optional), frame, plan, operation (needs "
            "operation_index from a prior 'plan' call), captures (BackBufferCopy/ScreenTexture "
            "pipeline operations), entity (needs entity -- matches by the entity_id that IS the "
            "RenderItem key), compare_modes (needs project -- compares the Edit-default and "
            "Play-style OrthographicCamera using the REAL construction math; supply "
            "edit_viewport_width/height and runtime_viewport_width/height with the actual live "
            "editor panel size and the actual game window size -- found via source_read on the "
            "project's __main__.py, since it's hardcoded there -- for a real, non-trivial "
            "comparison; without them both default to 400x300 and the comparison says so "
            "explicitly rather than pretending to be informative). 'cache' always reports "
            "available_statically=false: each call is a fresh isolated subprocess, so there is "
            "no persistent cache to inspect -- use editor_session (Phase 2F) for that."
        ),
        annotations=ToolAnnotations(
            title="Render Inspect",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def render_inspect(
        action: Literal[
            "capabilities", "entity", "frame", "plan", "operation", "captures", "cache", "compare_modes"
        ],
        project: str | None = None,
        scene: str | None = None,
        entity: str | None = None,
        operation_index: int | None = None,
        edit_viewport_width: int | None = None,
        edit_viewport_height: int | None = None,
        runtime_viewport_width: int | None = None,
        runtime_viewport_height: int | None = None,
        camera_width: float | None = None,
    ) -> ActionInspectResult:
        if action in {"entity", "frame", "plan", "operation", "captures", "compare_modes"} and not project:
            raise ValueError(f"action={action!r} requires 'project' (e.g. 'examples/blacksite_relay')")
        if action == "entity" and not entity:
            raise ValueError("action='entity' requires 'entity' (an entity_id or entity name)")
        if action == "operation" and operation_index is None:
            raise ValueError("action='operation' requires 'operation_index' (see action='plan' first)")

        executable, _ = resolve_configured_python(cfg)
        request: dict[str, Any] = {"op": "render_inspect", "action": action}
        if project:
            request["project"] = project
        if scene:
            request["scene"] = scene
        if entity:
            request["entity"] = entity
        if operation_index is not None:
            request["operation_index"] = operation_index
        if edit_viewport_width is not None:
            request["edit_viewport_width"] = edit_viewport_width
        if edit_viewport_height is not None:
            request["edit_viewport_height"] = edit_viewport_height
        if runtime_viewport_width is not None:
            request["runtime_viewport_width"] = runtime_viewport_width
        if runtime_viewport_height is not None:
            request["runtime_viewport_height"] = runtime_viewport_height
        if camera_width is not None:
            request["camera_width"] = camera_width

        try:
            raw = await run_static_op(executable, cfg.workspace.expra_root, request)
        except StaticInspectionError as exc:
            raise ValueError(f"{exc.kind}: {exc}") from exc

        return _to_action_result(raw)

    @server.tool(
        name="resource_trace",
        description=(
            "Trace one Expra asset end-to-end: logical ID (e.g. "
            "'assets://kenney/player_survivor_gun.png') -> resolved physical path -> content "
            "hash/size -> real Pygame decode via the actual PygameResourceProvider -> pixel "
            "dimensions/alpha presence -> that provider's last_failure, if any. Set "
            "include_preview=true to also get an actual MCP image preview, not just metadata."
        ),
        annotations=ToolAnnotations(
            title="Resource Trace",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def resource_trace(project: str, asset_id: str, include_preview: bool = False) -> ResourceTraceResult:
        executable, _ = resolve_configured_python(cfg)
        request = {
            "op": "resource_trace",
            "project": project,
            "asset_id": asset_id,
            "include_preview": include_preview,
        }

        try:
            raw = await run_static_op(executable, cfg.workspace.expra_root, request)
        except StaticInspectionError as exc:
            raise ValueError(f"{exc.kind}: {exc}") from exc

        preview_b64 = raw.pop("_preview_png_base64", None)
        result = ResourceTraceResult(**raw)

        if preview_b64 is None:
            return result

        image = Image(data=base64.b64decode(preview_b64), format="png")
        content: list[types.ContentBlock] = [
            types.TextContent(type="text", text=result.model_dump_json(indent=2)),
            image.to_image_content(),
        ]
        return types.CallToolResult(content=content, structuredContent=result.model_dump(mode="json"))  # type: ignore[return-value]

    @server.tool(
        name="render_snapshot",
        description=(
            "Render a project/scene through the REAL Expra renderer and return an actual MCP "
            "image (not a filename): mode='edit' calls the exact same render_editor_frame_to_image "
            "path the real editor uses (including its own preflight/diagnostics); mode='runtime' "
            "calls PygameRenderer.start()+render() directly, mirroring how a live game actually "
            "draws. Every call gets a run_id and writes the PNG under the configured artifact "
            "directory; pass compare_to_run_id (a prior render_snapshot's run_id) to get a real "
            "pixel-diff (same_dimensions, different_pixel_count, difference_ratio, "
            "mean_absolute_difference, bounding_box) against that baseline. Diagnostic log "
            "records captured during the render are saved under the same run_id -- follow up "
            "with diagnostics_analyze(run_id=...) rather than expecting them inline in bulk."
        ),
        annotations=ToolAnnotations(
            title="Render Snapshot",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def render_snapshot(
        project: str,
        scene: str | None = None,
        mode: Literal["edit", "runtime"] = "edit",
        viewport_width: int = 400,
        viewport_height: int = 300,
        camera_width: float = 20.0,
        elapsed: float = 0.0,
        compare_to_run_id: str | None = None,
    ) -> RenderSnapshotResult:
        executable, _ = resolve_configured_python(cfg)
        run_id = artifacts.new_run_id()

        request: dict[str, Any] = {
            "op": "render_snapshot",
            "project": project,
            "mode": mode,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "camera_width": camera_width,
            "elapsed": elapsed,
        }
        if scene:
            request["scene"] = scene
        if compare_to_run_id:
            baseline_path = cfg.artifacts_dir() / compare_to_run_id / "snapshot.png"
            if not baseline_path.is_file():
                raise ValueError(f"no artifact found for compare_to_run_id={compare_to_run_id!r} at {baseline_path}")
            request["compare_to_png_base64"] = base64.b64encode(baseline_path.read_bytes()).decode("ascii")

        try:
            raw = await run_static_op(executable, cfg.workspace.expra_root, request)
        except StaticInspectionError as exc:
            raise ValueError(f"{exc.kind}: {exc}") from exc

        png_b64 = raw.pop("_png_base64", None)
        diagnostics_records = raw.pop("diagnostics_records", [])
        comparison = raw.pop("comparison", None)

        artifact_path: str | None = None
        sha256: str | None = None
        png_bytes: bytes | None = None
        if png_b64 is not None:
            png_bytes = base64.b64decode(png_b64)
            path, digest = artifacts.write_snapshot_artifact(cfg.artifacts_dir(), run_id, png_bytes)
            artifact_path = str(path)
            sha256 = digest

        if diagnostics_records:
            artifacts.write_diagnostics_records(cfg.diagnostics_dir(), run_id, diagnostics_records)

        result = RenderSnapshotResult(
            run_id=run_id,
            mode=raw["mode"],
            executed_project_code=raw.get("executed_project_code", False),
            width=raw["width"],
            height=raw["height"],
            renderer=raw["renderer"],
            camera=raw["camera"],
            render_item_count=raw["render_item_count"],
            texture_ids=raw.get("texture_ids", []),
            pixel_renderer_success=raw["pixel_renderer_success"],
            failures=raw.get("failures", []),
            diagnostic_count=len(diagnostics_records),
            artifact_path=artifact_path,
            sha256=sha256,
            comparison=comparison,
        )

        if png_bytes is None:
            return result

        image = Image(data=png_bytes, format="png")
        content: list[types.ContentBlock] = [
            types.TextContent(type="text", text=result.model_dump_json(indent=2)),
            image.to_image_content(),
        ]
        return types.CallToolResult(content=content, structuredContent=result.model_dump(mode="json"))  # type: ignore[return-value]

    @server.tool(
        name="diagnostics_analyze",
        description=(
            "Aggregate the log records captured by a previous render_snapshot call (by run_id) "
            "into unique failure signatures with counts and first/last timestamps -- turns "
            "hundreds of repeated lines into a handful of structured entries instead of "
            "context-wasting raw output. The only current data source is render_snapshot's own "
            "captured diagnostics (run_checks in Phase 2E will feed this the same way)."
        ),
        annotations=ToolAnnotations(
            title="Diagnostics Analyze",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def diagnostics_analyze(run_id: str) -> DiagnosticsAnalyzeResult:
        try:
            raw = diagnostics.analyze_run(cfg.diagnostics_dir(), run_id)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        return DiagnosticsAnalyzeResult(**raw)

    @server.tool(
        name="runtime_probe",
        description=(
            "Drive a REAL headless Engine (core/engine.py -- zero pygame/Tk dependency) "
            "through a deterministic sequence of steps within one call, since scene/behaviour/"
            "physics state must persist across steps: play, pause, resume, stop, tick (dt), "
            "key_down/key_up (semantic input via the real InputMap, dispatched through the real "
            "Engine event queue -- never direct injection), inspect_entity, inspect_render, "
            "raycast, overlap. This is the ONE tool so far that genuinely executes project-"
            "authored Python: Behaviour subclasses are dynamically imported via the real "
            "ScriptRegistry (importlib.util.exec_module) the moment engine.play() runs, so "
            "every result reports executed_project_code=true. Gated to trusted_project_roots "
            "(default: only examples/) -- refuses anything else outright. One bad step is "
            "reported with ok=false and does not abort the remaining steps."
        ),
        annotations=ToolAnnotations(
            title="Runtime Probe",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def runtime_probe(
        project: str,
        steps: list[dict[str, Any]],
        scene: str | None = None,
    ) -> RuntimeProbeResult:
        if not project_trust.is_trusted_project(cfg, project):
            trusted = ", ".join(str(p) for p in project_trust.resolve_trusted_roots(cfg))
            raise ValueError(
                f"project {project!r} is not under a trusted_project_root ({trusted}); "
                "runtime_probe executes project-authored Behaviour code, so only explicitly "
                "trusted projects are allowed. Configure workspace.trusted_project_roots to add more."
            )

        executable, _ = resolve_configured_python(cfg)
        request: dict[str, Any] = {"op": "runtime_probe", "project": project, "steps": steps}
        if scene:
            request["scene"] = scene

        try:
            raw = await run_static_op(executable, cfg.workspace.expra_root, request)
        except StaticInspectionError as exc:
            raise ValueError(f"{exc.kind}: {exc}") from exc

        return RuntimeProbeResult(
            project=raw["project"],
            executed_project_code=raw.get("executed_project_code", True),
            steps=[RuntimeStepResult(**s) for s in raw.get("steps", [])],
        )

    @server.tool(
        name="run_checks",
        description=(
            "Run a NAMED development-check profile -- never an arbitrary shell command. Test "
            "profiles (renderer, blacksite, space_pong, neon_arena, physics, resources, "
            "backbuffer, editor_texture, export, full, full_xvfb, focused) run real pytest "
            "against real test files on disk and parse structured pass/fail/skip counts + "
            "failure summaries from --junitxml output. 'focused' requires test_target (e.g. "
            "'tests/test_renderer.py::test_name'), validated to stay inside expra-engine's own "
            "tests/ directory. Lint/type profiles (ruff, pyright, mypy) parse each tool's own "
            "structured output. compileall/diff_check/build_wheel round out the set. Full "
            "stdout/stderr is always written to a log file (log_path) instead of being dumped "
            "inline -- only bounded failure_summaries come back in the result."
        ),
        annotations=ToolAnnotations(
            title="Run Checks",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def run_checks_tool(
        profile: Literal[
            "renderer", "blacksite", "space_pong", "neon_arena", "physics", "resources",
            "backbuffer", "editor_texture", "export", "full", "full_xvfb", "focused",
            "ruff", "pyright", "mypy", "compileall", "diff_check", "build_wheel",
        ],
        test_target: str | None = None,
    ) -> CheckResult:
        executable, _ = resolve_configured_python(cfg)
        run_id = artifacts.new_run_id()
        log_dir = cfg.diagnostics_dir() / run_id

        try:
            raw = await run_checks.run_profile(
                profile=profile,
                executable=executable,
                expra_root=cfg.workspace.expra_root,
                log_dir=log_dir,
                test_target=test_target,
                timeout_seconds=float(cfg.execution.command_timeout_seconds),
            )
        except RunChecksError as exc:
            raise ValueError(str(exc)) from exc

        return CheckResult(**raw)

    @server.tool(
        name="export_inspect",
        description=(
            "Drive Expra's REAL exporter (export/exporter.py's GameExporter, export/plan.py's "
            "ExportPlan, export/verify.py's verify_export + forbidden-import scanner). Actions: "
            "'plan' validates an ExportPlan's configuration without running anything (safe, "
            "always allowed); 'verify' runs the real verification + forbidden-import scan "
            "against an EXISTING build_dir, read-only; 'export' runs the actual full pipeline "
            "-- which installs a Python runtime and downloads packages over the network -- and "
            "is refused unless execution.allow_network=true is set in the active config; use "
            "'plan' first to check configuration without that cost. 'plan'/'export' are gated "
            "to trusted_project_roots, same as runtime_probe."
        ),
        annotations=ToolAnnotations(
            title="Export Inspect",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def export_inspect(
        action: Literal["plan", "verify", "export"],
        project: str | None = None,
        output_dir: str | None = None,
        build_dir: str | None = None,
        target: Literal["linux", "windows"] = "linux",
        game_name: str | None = None,
        game_version: str | None = None,
        python_version: str = "3.12.4",
        arch: Literal["amd64", "arm64"] = "amd64",
        compile_bytecode: bool = True,
        runtime_profile: Literal["none", "pygame"] = "pygame",
    ) -> ExportInspectResult:
        request: dict[str, Any]

        if action == "verify":
            if not build_dir:
                raise ValueError("action='verify' requires 'build_dir'")
            request = {"op": "export_inspect", "action": action, "build_dir": build_dir}
        else:
            if not project:
                raise ValueError(f"action={action!r} requires 'project'")
            if not output_dir:
                raise ValueError(f"action={action!r} requires 'output_dir'")
            if not project_trust.is_trusted_project(cfg, project):
                trusted = ", ".join(str(p) for p in project_trust.resolve_trusted_roots(cfg))
                raise ValueError(f"project {project!r} is not under a trusted_project_root ({trusted})")
            if action == "export" and not cfg.execution.allow_network:
                return ExportInspectResult(
                    action=action,
                    success=False,
                    error=(
                        "action='export' refused: execution.allow_network is false in the active "
                        "config. A real export downloads a Python runtime and packages over the "
                        "network (GameExporter.export() calls packager.install_runtime/"
                        "install_packages) -- this is not a lightweight inspection. Set "
                        "execution.allow_network = true in .expra-mcp.toml to allow it, or use "
                        "action='plan' to validate the export configuration without running it."
                    ),
                )
            request = {
                "op": "export_inspect",
                "action": action,
                "project": project,
                "output_dir": output_dir,
                "target": target,
                "python_version": python_version,
                "arch": arch,
                "compile_bytecode": compile_bytecode,
                "runtime_profile": runtime_profile,
            }
            if game_name:
                request["game_name"] = game_name
            if game_version:
                request["game_version"] = game_version

        executable, _ = resolve_configured_python(cfg)
        try:
            raw = await run_static_op(executable, cfg.workspace.expra_root, request)
        except StaticInspectionError as exc:
            raise ValueError(f"{exc.kind}: {exc}") from exc

        return ExportInspectResult(**raw)

    @server.tool(
        name="editor_session",
        description=(
            "Operate a REAL Expra EditorWindow (genuine Tk, not simulated) through a "
            "long-lived worker subprocess. action='start' launches the worker (no project "
            "argument -- always follow with 'open_project'); reports "
            "editor_session_available=false with a reason if no usable display exists and "
            "Xvfb isn't available, rather than failing confusingly. 'open_project' loads a "
            "project exactly like File > Open Project (executes project-authored Behaviour "
            "code, gated to trusted_project_roots). 'play'/'pause'/'resume'/'stop' drive the "
            "real editor Play button handlers -- 'stop' provably restores the untouched edit "
            "scene. 'send_key' uses genuine Tk event_generate (phase='down'|'up'), exercising "
            "the real keyboard binding path a human press would take -- never direct input "
            "injection. 'wait' (duration_ms) lets the real RuntimePreviewLoop auto-tick in "
            "real time while the event loop keeps pumping. 'select_entity', 'inspect' "
            "(entity optional -- omit for a scene summary), 'inspect_render', 'state', and "
            "'capture_viewport' (returns an actual MCP image of the pygame-rendered layer when "
            "one exists -- Canvas-drawn overlays like grid/collider outlines are never included "
            "-- or, when the editor is genuinely using Canvas-vector fallback instead of the "
            "pixel path, structured data instead of an image: "
            "{available: false, pixel_layer_active: false, fallback_active: true, reason: "
            "'unsupported primitive: ...'}; Canvas fallback is never reported as a successful "
            "pixel render) round out the action set. 'observability_snapshot' returns the live "
            "session's single shared ObservabilityWatcher (app/ui/runtime/render/editor metrics "
            "together) as data.metrics -- pass prefix='runtime:' etc. to filter, "
            "reset_observations=true to clear history before returning (empty snapshot). "
            "'frame_scene' calls the real ViewportPanel.frame_scene() (or frame_selected() with "
            "selection_only=true) -- reports framed=false rather than an error when there's "
            "nothing to frame yet (no scene loaded, or nothing selected). 'open_scene' (needs "
            "'scene', a project-relative path) switches the edit scene within the current "
            "project, exactly like File > Open Scene. 'new_scene'/'duplicate_scene' (need "
            "'name') create a scene the same way File > New/Duplicate Scene does. 'save_scene' "
            "saves through the canonical Project.save_scene() path (never leaks resolved "
            "scene-instance content into the file). 'run_project' plays from the project's "
            "start scene regardless of what's currently open, restoring the prior scene on the "
            "next 'stop' -- exactly like the Run Project toolbar button. Always call 'close' "
            "when done -- a worker whose stdin closes unexpectedly shuts itself down, but "
            "that's a safety net, not a substitute."
        ),
        annotations=ToolAnnotations(
            title="Editor Session",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def editor_session(
        action: Literal[
            "start", "open_project", "state", "play", "pause", "resume", "stop",
            "send_key", "wait", "select_entity", "frame_scene", "capture_viewport",
            "inspect", "inspect_render", "observability_snapshot", "close",
            "open_scene", "new_scene", "save_scene", "duplicate_scene", "run_project",
        ],
        session_id: str | None = None,
        project: str | None = None,
        scene: str | None = None,
        entity: str | None = None,
        key: str | None = None,
        phase: Literal["down", "up"] = "down",
        duration_ms: int = 250,
        prefix: str | None = None,
        reset_observations: bool = False,
        name: str | None = None,
        selection_only: bool = False,
    ) -> EditorSessionResult:
        if action == "start":
            new_id, data = await editor_sessions.start(expra_root=cfg.workspace.expra_root)
            available = bool(data.pop("editor_session_available", True))
            reason = data.pop("reason", None)
            return EditorSessionResult(
                session_id=new_id, action=action, editor_session_available=available, reason=reason, data=data
            )

        if not session_id:
            raise ValueError(f"action={action!r} requires 'session_id' (call action='start' first)")

        params: dict[str, Any] = {}
        if action == "open_project":
            if not project:
                raise ValueError("action='open_project' requires 'project'")
            if not project_trust.is_trusted_project(cfg, project):
                trusted = ", ".join(str(p) for p in project_trust.resolve_trusted_roots(cfg))
                raise ValueError(f"project {project!r} is not under a trusted_project_root ({trusted})")
            params = {"expra_root": str(cfg.workspace.expra_root), "project": project}
            if scene:
                params["scene"] = scene
        elif action == "send_key":
            if not key:
                raise ValueError("action='send_key' requires 'key'")
            params = {"key": key, "phase": phase}
        elif action == "wait":
            params = {"duration_ms": duration_ms}
        elif action == "select_entity":
            if not entity:
                raise ValueError("action='select_entity' requires 'entity'")
            params = {"entity": entity}
        elif action == "inspect_render":
            if not entity:
                raise ValueError("action='inspect_render' requires 'entity'")
            params = {"entity": entity}
        elif action == "frame_scene":
            params = {"selection_only": selection_only}
        elif action == "open_scene":
            if not scene:
                raise ValueError("action='open_scene' requires 'scene' (project-relative path)")
            params = {"relative_path": scene}
        elif action in ("new_scene", "duplicate_scene"):
            if not name:
                raise ValueError(f"action={action!r} requires 'name'")
            params = {"name": name}
        elif action == "inspect" and entity:
            params = {"entity": entity}
        elif action == "observability_snapshot":
            params = {"reset": reset_observations}
            if prefix:
                params["prefix"] = prefix

        try:
            response = await editor_sessions.send(session_id, action, params)
        except EditorSessionError as exc:
            raise ValueError(str(exc)) from exc

        if not response.get("ok"):
            raise ValueError(response.get("error", f"editor_session action {action!r} failed"))

        data = response.get("data", {})

        if action == "capture_viewport":
            png_b64 = data.pop("_png_base64", None)
            result = EditorSessionResult(session_id=session_id, action=action, data=data)
            if png_b64 is None:
                return result
            image = Image(data=base64.b64decode(png_b64), format="png")
            content: list[types.ContentBlock] = [
                types.TextContent(type="text", text=result.model_dump_json(indent=2)),
                image.to_image_content(),
            ]
            return types.CallToolResult(content=content, structuredContent=result.model_dump(mode="json"))  # type: ignore[return-value]

        return EditorSessionResult(session_id=session_id, action=action, data=data)

    @server.tool(
        name="performance_probe",
        description=(
            "Distinguish a bounded retry/log flood from an actual retained-resource leak with "
            "real measurements, never a guess. 'render_stress' (needs project) repeatedly "
            "renders headlessly, measuring resource-cache size, logger handler count, and "
            "unique-vs-total diagnostic occurrences before/after (optional track_memory=true "
            "adds a tracemalloc delta). 'resource_cache' (needs project + asset_ids) repeatedly "
            "resolves the same assets, checking the cache stays near len(asset_ids) rather than "
            "growing with iteration count. 'editor_redraw_stress' (needs session_id from a "
            "started editor_session) repeatedly redraws the REAL live Tk viewport, measuring "
            "Canvas item count and PhotoImage count via real Tcl introspection ('image names'). "
            "Every action reports verdict: 'bounded' | 'growing' | 'inconclusive', backed by the "
            "actual before/after numbers -- never asserts a leak without retention evidence."
        ),
        annotations=ToolAnnotations(
            title="Performance Probe",
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=False,
        ),
    )
    async def performance_probe(
        action: Literal["render_stress", "resource_cache", "editor_redraw_stress"],
        project: str | None = None,
        scene: str | None = None,
        session_id: str | None = None,
        iterations: int = 30,
        viewport_width: int = 400,
        viewport_height: int = 300,
        camera_width: float = 20.0,
        track_memory: bool = False,
        asset_ids: list[str] | None = None,
    ) -> PerformanceProbeResult:
        if action == "editor_redraw_stress":
            if not session_id:
                raise ValueError(
                    "action='editor_redraw_stress' requires 'session_id' "
                    "(call editor_session action='start' first)"
                )
            try:
                response = await editor_sessions.send(session_id, "performance_probe", {"iterations": iterations})
            except EditorSessionError as exc:
                raise ValueError(str(exc)) from exc
            if not response.get("ok"):
                raise ValueError(response.get("error", "performance_probe failed"))
            return PerformanceProbeResult(action=action, **response.get("data", {}))

        if action == "resource_cache":
            if not project or not asset_ids:
                raise ValueError("action='resource_cache' requires 'project' and 'asset_ids'")
            executable, _ = resolve_configured_python(cfg)
            request: dict[str, Any] = {
                "op": "performance_probe",
                "action": action,
                "project": project,
                "asset_ids": asset_ids,
                "iterations": iterations,
            }
            try:
                raw = await run_static_op(executable, cfg.workspace.expra_root, request)
            except StaticInspectionError as exc:
                raise ValueError(f"{exc.kind}: {exc}") from exc
            return PerformanceProbeResult(**raw)

        if action == "render_stress":
            if not project:
                raise ValueError("action='render_stress' requires 'project'")
            executable, _ = resolve_configured_python(cfg)
            request = {
                "op": "performance_probe",
                "action": action,
                "project": project,
                "viewport_width": viewport_width,
                "viewport_height": viewport_height,
                "camera_width": camera_width,
                "iterations": iterations,
                "track_memory": track_memory,
            }
            if scene:
                request["scene"] = scene
            try:
                raw = await run_static_op(executable, cfg.workspace.expra_root, request)
            except StaticInspectionError as exc:
                raise ValueError(f"{exc.kind}: {exc}") from exc
            return PerformanceProbeResult(**raw)

        raise ValueError(f"unknown performance_probe action: {action!r}")

    @server.prompt(
        name="debug-renderer",
        title="Debug a renderer/visual issue",
        description="Step an agent through diagnosing a renderer/visual bug using this MCP's own real-evidence tools, in the right order.",
    )
    def debug_renderer_prompt(project: str, entity: str = "") -> str:
        entity_clause = f" focused on the entity {entity!r}" if entity else ""
        return (
            f"Debug a renderer/visual issue in project {project!r}{entity_clause} using expra-mcp's "
            "own tools, in this order -- do not skip steps or assume success without evidence:\n"
            "1. workspace_doctor -- confirm READY before trusting anything else.\n"
            "2. expra_inspect(action='entity', project=..., entity=...) -- static component data "
            "(transform, primitive/sprite/text/etc) with zero project-code execution.\n"
            "3. render_inspect(action='entity', project=..., entity=...) -- trace "
            "Component -> world transform -> RenderItem using the REAL extract_render_frame, not "
            "a reimplementation.\n"
            "4. render_inspect(action='capabilities', project=...) -- confirm the renderer "
            "backend actually declares support for what this entity needs "
            "(texture/nine_slice/outline/etc).\n"
            "5. If a sprite/texture is involved: resource_trace(project=..., asset_id=..., "
            "include_preview=true) -- confirm it actually decodes, with real pixel dimensions "
            "and alpha, not just that the file exists.\n"
            "6. render_snapshot(project=..., mode='edit') and mode='runtime' -- get REAL pixels, "
            "never assume visual success; compare the two.\n"
            "7. diagnostics_analyze(run_id=<the snapshot's run_id>) -- aggregate any captured "
            "failures into unique signatures with counts, instead of reading raw logs.\n"
            "8. If the bug only appears live (not statically): use runtime_probe or "
            "editor_session to reproduce it with real ticks/input, then repeat steps 3-6 against "
            "the live state.\n"
            "Do not report a fix as working without a fresh render_snapshot + diagnostics_analyze "
            "pass confirming it, and do not call something a memory leak without a "
            "performance_probe retention measurement."
        )

    @server.prompt(
        name="mine-reference",
        title="Mine a reference engine for a design",
        description="Guide an agent through researching how a reference engine solved a concept, then mapping the invariant (not the framework) onto Expra's real ownership.",
    )
    def mine_reference_prompt(concept: str, subsystem: str = "", references: str = "godot") -> str:
        subsystem_clause = f" for Expra's {subsystem!r} subsystem" if subsystem else ""
        return (
            f"Research how {concept!r} is handled in the reference engine(s) [{references}]{subsystem_clause}, "
            "then design an Expra-native fix -- adapt the invariant, never transliterate the "
            "framework:\n"
            f"1. source_search(repos=[{references!r}], query=<the real symbol/concept name>) -- "
            "find actual matches, not assumptions about what a real engine 'probably' does.\n"
            "2. source_read(repo=..., relative_path=..., start_line=..., end_line=...) on the "
            "real matches -- read the actual implementation, not just the one matching line.\n"
            "3. Follow callers/callees with further source_search calls in the same repo until "
            "the real invariant (not the specific API shape) is understood.\n"
            "4. source_search(repos=['expra'], query=<the analogous Expra concept>) -- find how "
            "Expra currently owns this, or confirm it doesn't yet.\n"
            "5. source_read the current Expra implementation fully before proposing any change.\n"
            "6. Design the fix in terms of Expra's own architecture (its real classes: Scene/"
            "Entity/Component/RenderItem/Engine/etc, confirmed via source_read) -- port the "
            "concept, never the reference engine's own machinery (no RID/RenderingDevice-style "
            "constructs, no framework transliteration).\n"
            "7. Verify with render_inspect/render_snapshot/runtime_probe against real Expra data, "
            "not the reference engine's behavior.\n"
            "The reference source is evidence for a design decision, not a template to copy."
        )

    @server.prompt(
        name="tk-regression",
        title="Diagnose a Tk/editor scheduling regression",
        description="Guide an agent through diagnosing a Tk/editor scheduling, threading, or coordinator regression by mining exp_ui and Expra's current coordinators.",
    )
    def tk_regression_prompt(symptom: str) -> str:
        return (
            f"Diagnose this Tk/editor regression: {symptom!r}. Prioritize exp_ui (the original "
            "AppCoordinator/UICoordinator implementation) and Expra's current coordinators over "
            "inventing a new pattern:\n"
            "1. source_search(repos=['expra'], query='UICoordinator') and query='AppCoordinator' "
            "-- read Expra's current coordinators/app_coordinator.py and "
            "coordinators/ui_coordinator.py in full via source_read before touching anything.\n"
            "2. source_search(repos=['exp_ui'], query=<the matching concept: 'render_coordinator', "
            "'action_coordinator', 'window_lifecycle', etc>) -- read the ORIGINAL implementation "
            "this was adapted from; identify which invariant it enforces (staleness rejection, "
            "generation numbers, coalescing, main-thread-only Tk mutation, shutdown order).\n"
            "3. Determine whether current Expra preserves that invariant or has diverged from it "
            "-- this is usually where the regression actually lives.\n"
            "4. If the regression involves the live editor specifically, reproduce it with a "
            "real editor_session (start -> open_project -> the exact repro steps -> state/inspect) "
            "rather than reasoning about it in the abstract -- editor_session drives the real "
            "EditorWindow's real Tk main-thread event loop.\n"
            "5. Never call widget.after_idle() from a worker thread, and never mutate Tk objects "
            "off the main thread -- confirm any proposed fix respects "
            "ui/editor_window.py's own documented threading invariant.\n"
            "Root-cause the specific invariant that broke; don't just paper over the symptom."
        )

    @server.prompt(
        name="release-check",
        title="Pre-release evidence check",
        description="Guide an agent through a pre-release check combining source, installed-package, and export evidence -- never a single signal alone.",
    )
    def release_check_prompt(project: str = "") -> str:
        project_clause = project or "the configured default_project"
        return (
            "Before calling a change release-ready, gather evidence from ALL of these -- no "
            "single one is sufficient on its own:\n"
            "1. workspace_doctor -- confirm expra_engine imports from the configured SOURCE tree "
            "(not a stale installed package) and the overall readiness verdict is READY.\n"
            "2. repo_inspect(action='status') and action='diff' -- confirm what's actually "
            "changed and that nothing unexpected is staged/unstaged.\n"
            "3. run_checks with the profiles relevant to the change (e.g. 'renderer', "
            f"{project_clause!r}, 'physics', 'resources') plus at least 'ruff', 'pyright', and "
            "'mypy' -- read the real structured pass/fail counts, not just exit codes.\n"
            "4. run_checks(profile='full') or 'full_xvfb' for the complete regression suite.\n"
            "5. render_snapshot + diagnostics_analyze against the affected example project(s) -- "
            "real pixels and real aggregated diagnostics, not assumptions.\n"
            f"6. export_inspect(action='plan', project={project_clause!r}, output_dir=...) to "
            "validate export configuration; action='export' only with explicit user consent "
            "given it downloads a Python runtime and packages over the network "
            "(execution.allow_network must be true).\n"
            "7. export_inspect(action='verify', build_dir=...) on any resulting build -- real "
            "forbidden-import scan and manifest validation, not an assumption that export "
            "succeeded just because no exception was raised.\n"
            "A change is release-ready only when source, test, and (if applicable) export "
            "evidence all agree -- report which of these you actually checked, not just the ones "
            "that passed."
        )

    return server
