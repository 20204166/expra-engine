"""Human-readable project entrypoint and Run Project diagnostics."""

from __future__ import annotations

from expra_engine.messages._format import bounded_text


def project_script_entrypoint_required() -> str:
    return "project script entry point must be a non-empty relative path"


def project_script_entrypoint_outside_project() -> str:
    return "project script entry point must remain inside the project"


def project_script_entrypoint_escapes_project() -> str:
    return "project script entry point escapes the project"


def project_script_entrypoint_missing(entrypoint: str) -> str:
    return f"Script entry point not found: {bounded_text(entrypoint, 256)}"


def project_launch_failed(launcher: str, gameplay_entrypoint: str | None, detail: str) -> str:
    script = bounded_text(launcher, 256)
    document = bounded_text(gameplay_entrypoint, 256) if gameplay_entrypoint else "(not set)"
    return f"[Editor] Could not launch {script} for gameplay entrypoint {document}: {bounded_text(detail)}"


def project_script_start_failed(
    script_entrypoint: str,
    gameplay_entrypoint: str | None,
    detail: str,
) -> str:
    script = bounded_text(script_entrypoint, 256)
    document = bounded_text(gameplay_entrypoint, 256) if gameplay_entrypoint else "(not set)"
    return (
        f"[Editor] Could not start project launcher {script} "
        f"for gameplay entrypoint {document}: {bounded_text(detail)}"
    )


def project_started(launcher: str, gameplay_entrypoint: str | None) -> str:
    script = bounded_text(launcher, 256)
    document = bounded_text(gameplay_entrypoint, 256) if gameplay_entrypoint else "(not set)"
    return f"[Editor] Started project launcher: {script}; gameplay entrypoint: {document}"


def project_exited(
    return_code: int,
    launcher: str,
    gameplay_entrypoint: str | None,
    output_tail: str = "",
) -> str:
    status = "exited" if return_code == 0 else f"exited with status {return_code}"
    script = bounded_text(launcher, 256)
    document = bounded_text(gameplay_entrypoint, 256) if gameplay_entrypoint else "(not set)"
    message = f"[Editor] Project {status} (launcher {script}; gameplay entrypoint {document})"
    detail = bounded_text(output_tail.strip(), 2048) if return_code != 0 else ""
    return f"{message}\n{detail}" if detail else message


def project_entrypoint_document_unsupported() -> str:
    return "Project entrypoint must be a Scene, Level, or World"


def project_engine_could_not_play() -> str:
    return "Project Engine could not enter Play"
