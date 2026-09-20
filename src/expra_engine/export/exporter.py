"""GameExporter — pure export orchestrator.

No tkinter, no ttkbootstrap. Cancellation via threading.Event.
Progress via injected Callable[[ExportProgressEvent], None].

Atomic build contract:
  build in temp dir -> verify -> promote
  If anything fails, the previous export at output_dir is NOT disturbed.
"""

from __future__ import annotations

import datetime
import shutil
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from expra_engine.export.bytecode import BytecodeCompiler
from expra_engine.export.events import ExportPhase, ExportProgressEvent
from expra_engine.export.manifest import AssetManifest, BuildManifest
from expra_engine.export.packager import LinuxPackager, TargetPackager, WindowsPackager
from expra_engine.export.plan import ExportPlan, ExportTarget
from expra_engine.export.verify import verify_export


class ExportError(RuntimeError):
    pass


_PROGRESS_CALLBACK = Callable[[ExportProgressEvent], None]


class GameExporter:
    """Orchestrates the full game export pipeline.

    Inject a custom packager for unit tests (avoids real network calls).
    """

    def __init__(self, *, packager: TargetPackager | None = None) -> None:
        self._packager_override = packager

    def export(
        self,
        plan: ExportPlan,
        *,
        cancel: threading.Event,
        progress: _PROGRESS_CALLBACK | None = None,
    ) -> Path:
        """Run the full export. Returns the promoted build directory.

        Raises ExportError on failure or cancellation. Previous build is
        NOT disturbed on failure (atomic temp -> promote).
        """
        emit = _make_emitter(progress)
        packager = self._packager_override or _select_packager(plan.target)

        emit(ExportPhase.PLANNING, "Preparing export plan", 0)

        plan.output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = plan.game_name.replace(" ", "_")
        final_dir = plan.output_dir / f"{safe_name}_{plan.target.value}"

        with tempfile.TemporaryDirectory(prefix="expra_export_") as tmpstr:
            tmp_build = Path(tmpstr) / safe_name
            tmp_build.mkdir(parents=True)

            try:
                self._run_pipeline(plan, tmp_build, safe_name, packager, cancel, emit)
            except Exception as exc:
                emit(ExportPhase.FAILED, str(exc), 0)
                raise ExportError(str(exc)) from exc

            if cancel.is_set():
                emit(ExportPhase.CANCELLED, "Export cancelled", 0)
                raise ExportError("Export cancelled")

            emit(ExportPhase.VERIFYING, "Verifying build integrity", 90)
            verify_export(tmp_build)

            emit(ExportPhase.PROMOTING, "Promoting to output directory", 95)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            shutil.copytree(tmp_build, final_dir)

        emit(ExportPhase.DONE, f"Export complete: {final_dir}", 100)
        return final_dir

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        plan: ExportPlan,
        build_dir: Path,
        safe_name: str,
        packager: TargetPackager,
        cancel: threading.Event,
        emit: Callable[[ExportPhase, str, int], None],
    ) -> None:
        game_source_dir = build_dir / safe_name
        runtime_dir = build_dir / "runtime"

        if plan.target == ExportTarget.WINDOWS:
            python_dir = runtime_dir / "python"
            site_packages = python_dir / "Lib" / "site-packages"
        else:
            python_dir = runtime_dir
            site_packages = runtime_dir / "lib" / "python3" / "site-packages"

        # Stage 1: collect assets
        emit(ExportPhase.COLLECTING_ASSETS, "Collecting game assets", 10)
        if cancel.is_set():
            return
        asset_manifest = AssetManifest.collect(
            plan.project_dir,
            extra_exclude_patterns=plan.exclude_patterns,
            include_source=True,
        )
        _copy_assets(plan.project_dir, game_source_dir, asset_manifest)

        # Stage 2: bytecode (optional)
        if plan.compile_bytecode:
            emit(ExportPhase.COMPILING_BYTECODE, "Compiling bytecode", 20)
            if cancel.is_set():
                return
            compiler = BytecodeCompiler()
            compiler.compile(
                game_source_dir,
                game_source_dir,
                cancel=cancel,
                progress=lambda msg: emit(ExportPhase.COMPILING_BYTECODE, msg, 25),
            )
            for py_file in game_source_dir.rglob("*.py"):
                py_file.unlink()

        # Stage 3: install runtime
        emit(ExportPhase.COPYING_RUNTIME, "Installing Python runtime", 40)
        if cancel.is_set():
            return
        cache_root = plan.output_dir / ".cache"
        packager.install_runtime(
            plan.python_version,
            plan.arch.value,
            python_dir,
            cache_dir=cache_root / "python",
            cancel=cancel,
            progress=lambda msg: emit(ExportPhase.COPYING_RUNTIME, msg, 50),
        )

        # Stage 4: resolve and install packages
        emit(ExportPhase.RESOLVING_DEPS, "Resolving dependencies", 60)
        if cancel.is_set():
            return
        packages = list(plan.extra_packages)
        packager.install_packages(
            packages,
            plan.python_version,
            plan.arch.value,
            site_packages,
            cache_dir=cache_root / "wheels",
            cancel=cancel,
            progress=lambda msg: emit(ExportPhase.RESOLVING_DEPS, msg, 65),
        )

        # Stage 5: write manifests
        emit(ExportPhase.WRITING_MANIFESTS, "Writing manifests", 80)
        (build_dir / "asset_manifest.json").write_text(asset_manifest.to_json())

        build_manifest = BuildManifest(
            game_name=plan.game_name,
            game_version=plan.game_version,
            engine_version=_engine_version(),
            target=plan.target.value,
            python_version=plan.python_version,
            arch=plan.arch.value,
            compile_bytecode=plan.compile_bytecode,
            entry_point=plan.entry_point,
            build_timestamp=datetime.datetime.now(tz=datetime.UTC).isoformat(),
        )
        (build_dir / "build_manifest.json").write_text(build_manifest.to_json())

        # Stage 6: launchers
        packager.make_launcher(
            build_dir, plan.game_name, plan.entry_point, safe_name,
            is_pyc=plan.compile_bytecode, debug=False,
        )
        if plan.debug_launcher:
            packager.make_launcher(
                build_dir, plan.game_name, plan.entry_point, safe_name,
                is_pyc=plan.compile_bytecode, debug=True,
            )


# ------------------------------------------------------------------
# Module-level helpers (not on the class — keep GameExporter pure)
# ------------------------------------------------------------------


def _copy_assets(source: Path, dest: Path, manifest: AssetManifest) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for entry in manifest.entries:
        src = source / entry.path
        dst = dest / entry.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _select_packager(target: ExportTarget) -> TargetPackager:
    if target == ExportTarget.WINDOWS:
        return WindowsPackager()
    return LinuxPackager()


def _engine_version() -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version("expra_engine")
    except Exception:  # noqa: BLE001
        return "unknown"


def _make_emitter(
    progress: _PROGRESS_CALLBACK | None,
) -> Callable[[ExportPhase, str, int], None]:
    def emit(phase: ExportPhase, message: str, percent: int) -> None:
        if progress is not None:
            progress(ExportProgressEvent(phase=phase, message=message, percent=percent))

    return emit
