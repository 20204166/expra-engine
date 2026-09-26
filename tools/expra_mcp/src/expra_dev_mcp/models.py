"""Structured result models returned by expra-mcp tools.

Every tool returns a pydantic model so the MCP SDK auto-derives an
``output_schema`` and populates ``structured_content`` alongside the
human-readable ``TextContent`` -- never a prose-only blob (spec section 5/6).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ServerInfo(BaseModel):
    name: str
    version: str
    config_path: str
    artifact_directory: str
    diagnostics_directory: str


class PythonIdentity(BaseModel):
    role: str  # "mcp_server" | "expra"
    executable: str
    version: str
    resolved_via: str  # "self" | "auto:.venv" | "config:explicit" | "fallback:current_interpreter"


class ExpraIdentity(BaseModel):
    root: str
    git_commit: str | None = None
    git_dirty: bool | None = None
    module_file: str | None = None
    module_version: str | None = None
    imported_from_configured_source: bool | None = None
    import_error: str | None = None


class PygameIdentity(BaseModel):
    installed: bool
    version: str | None = None
    module_file: str | None = None
    error: str | None = None


class TkIdentity(BaseModel):
    available: bool
    tcl_tk_version: str | None = None
    display: str | None = None
    wayland_display: str | None = None
    error: str | None = None


class ToolStatus(BaseModel):
    name: str
    available: bool
    version: str | None = None
    path: str | None = None


class ReferenceStatus(BaseModel):
    id: str
    path: str
    exists: bool
    read_only: bool
    domains: list[str] = Field(default_factory=list)
    git_revision: str | None = None
    is_git_checkout: bool = False


class ProjectStatus(BaseModel):
    id: str
    path: str
    exists: bool


class WorkspaceDoctorResult(BaseModel):
    readiness: str  # "READY" | "READY_WITH_LIMITATIONS" | "NOT_READY"
    reasons: list[str] = Field(default_factory=list)
    server: ServerInfo
    mcp_server_python: PythonIdentity
    expra_python: PythonIdentity
    expra: ExpraIdentity
    pygame: PygameIdentity
    tk: TkIdentity
    tools: list[ToolStatus]
    default_project: ProjectStatus | None = None
    references: list[ReferenceStatus] = Field(default_factory=list)


class SourceMatch(BaseModel):
    repository: str
    relative_path: str
    line_number: int
    match: str
    context: list[str] = Field(default_factory=list)
    context_start_line: int
    language: str | None = None


class SourceSearchResult(BaseModel):
    query: str
    mode: str
    repos_searched: list[str]
    matches: list[SourceMatch]
    truncated: bool
    backend: str  # "ripgrep" | "pure_python"


class SourceReadResult(BaseModel):
    repo: str
    path: str
    revision: str | None = None
    start_line: int
    end_line: int
    total_lines: int
    truncated: bool
    content: str


class GitFileChange(BaseModel):
    status: str
    path: str


class RepoInspectResult(BaseModel):
    action: str
    branch: str | None = None
    head_commit: str | None = None
    dirty: bool | None = None
    changed_files: list[GitFileChange] = Field(default_factory=list)
    diff_stat: str | None = None
    diff: str | None = None
    recent_commits: list[str] = Field(default_factory=list)
    error: str | None = None


class ActionInspectResult(BaseModel):
    """Shared shape for expra_inspect and render_inspect: both are one
    domain-specific tool with an ``action`` parameter whose payload shape
    is inherently per-action (project vs. entity vs. render frame, ...),
    so the action-specific fields live in ``data`` rather than forcing a
    single rigid schema across nine/seven unrelated action types.
    """

    action: str
    executed_project_code: bool = False
    available_statically: bool = True
    note: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ResourceTraceResult(BaseModel):
    logical_id: str
    exists: bool
    decode_status: str
    resolved_path: str | None = None
    content_size: int | None = None
    content_hash: str | None = None
    modified_ns: int | None = None
    extension: str | None = None
    decode_error: str | None = None
    pixel_width: int | None = None
    pixel_height: int | None = None
    has_alpha: bool | None = None
    cache_key: str | None = None
    last_provider_failure: dict[str, str] | None = None


class RenderSnapshotResult(BaseModel):
    run_id: str
    mode: str
    executed_project_code: bool = False
    width: int
    height: int
    renderer: str
    camera: dict[str, Any]
    render_item_count: int
    texture_ids: list[str] = Field(default_factory=list)
    pixel_renderer_success: bool
    failures: list[str] = Field(default_factory=list)
    diagnostic_count: int = 0
    artifact_path: str | None = None
    sha256: str | None = None
    comparison: dict[str, Any] | None = None


class DiagnosticFailure(BaseModel):
    signature: str
    logger: str
    level: str
    message_template: str
    count: int
    first_timestamp: float
    last_timestamp: float
    sample: str


class DiagnosticsAnalyzeResult(BaseModel):
    run_id: str
    raw_record_count: int
    unique_failures: int
    failures: list[DiagnosticFailure] = Field(default_factory=list)


class RuntimeStepResult(BaseModel):
    index: int
    action: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class RuntimeProbeResult(BaseModel):
    project: str
    executed_project_code: bool = True
    steps: list[RuntimeStepResult] = Field(default_factory=list)


class ExportInspectResult(BaseModel):
    action: str
    plan_valid: bool | None = None
    plan_error: str | None = None
    plan: dict[str, Any] | None = None
    success: bool | None = None
    error: str | None = None
    build_dir: str | None = None
    build_manifest: dict[str, Any] | None = None
    asset_manifest: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    forbidden_imports: list[str] = Field(default_factory=list)


class EditorSessionResult(BaseModel):
    session_id: str
    action: str
    editor_session_available: bool = True
    reason: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class PerformanceProbeResult(BaseModel):
    action: str
    iterations: int = 0
    duration_seconds: float = 0.0
    verdict: str = "measured"  # "bounded" | "growing" | "inconclusive" | "measured"
    resource: str | None = None
    format: str | None = None
    kind: str | None = None
    bytes: int | None = None
    entities: int | None = None
    components: int | None = None
    instances: int | None = None
    sha256: str | None = None
    first_load_total_ms: float | None = None
    observer_enabled: bool | None = None
    stages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    failed_stage: str | None = None
    resource_cache_count_before: int | None = None
    resource_cache_count_after: int | None = None
    logger_handler_count_before: int | None = None
    logger_handler_count_after: int | None = None
    unique_diagnostic_signatures: int | None = None
    total_diagnostic_occurrences: int | None = None
    memory_delta_kb: float | None = None
    canvas_item_count_before: int | None = None
    canvas_item_count_after: int | None = None
    photoimage_count_before: int | None = None
    photoimage_count_after: int | None = None
    asset_count: int | None = None


class CheckResult(BaseModel):
    profile: str
    success: bool
    exit_code: int | None = None
    timed_out: bool = False
    duration_seconds: float
    tests_collected: int | None = None
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    warnings: int | None = None
    failure_summaries: list[str] = Field(default_factory=list)
    log_path: str | None = None
    artifact_path: str | None = None
