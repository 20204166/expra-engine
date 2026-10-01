"""Setuptools entry point for optional, bundled native wheel builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from expra_engine._release import native_source_manifest  # noqa: E402


class ExpraBuildPy(build_py):
    """Include native build inputs in wheel manifests for version tracking."""

    def run(self) -> None:
        super().run()
        manifest = Path(self.build_lib) / "expra_engine" / "_native_source_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(native_source_manifest(ROOT))

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = super().get_outputs(include_bytecode)
        manifest = str(Path(self.build_lib) / "expra_engine" / "_native_source_manifest.json")
        if Path(manifest).is_file() and manifest not in outputs:
            outputs.append(manifest)
        return outputs


rust_extensions = []
rust_mode = os.environ.get("EXPRA_BUILD_RUST", "0").strip().lower()
if rust_mode not in {"0", "1"}:
    raise RuntimeError("EXPRA_BUILD_RUST must be '0' (Python wheel) or '1' (native wheel)")
if rust_mode == "1":
    os.environ["DIST_EXTRA_CONFIG"] = str(ROOT / "setup.cfg")
    from setuptools_rust import Binding, RustExtension  # type: ignore[reportMissingImports]

    rust_extensions.append(
        RustExtension(
            "expra_render_math",
            path=str(ROOT / "native" / "expra_render_math" / "Cargo.toml"),
            binding=Binding.PyO3,
            features=["abi3-py312"],
            cargo_manifest_args=["--locked"],
        )
    )

setup(
    rust_extensions=rust_extensions,
    cmdclass={"build_py": ExpraBuildPy},
)
