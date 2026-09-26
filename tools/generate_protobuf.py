"""Generate checked-in protobuf bindings for Expra's document schema.

Normal runtime imports only the generated Python modules. Generation is an
explicit development command and is deterministic for a fixed protoc version.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
OUTPUT_DIR = ROOT / "src" / "expra_engine" / "schema" / "generated"


def _generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "__init__.py").write_text(
        '"""Generated protobuf bindings. Regenerate with tools/generate_protobuf.py."""\n',
        encoding="utf-8",
    )
    result = protoc.main(
        (
            "protoc",
            f"-I{SCHEMA_DIR}",
            f"--python_out={output_dir}",
            str(SCHEMA_DIR / "common.proto"),
            str(SCHEMA_DIR / "scene.proto"),
            str(SCHEMA_DIR / "level.proto"),
        )
    )
    if result != 0:
        raise SystemExit(result)
    # grpc_tools emits sibling imports as top-level imports. Checked-in
    # bindings live in a package, so normalize those imports deterministically.
    for module in ("scene_pb2.py", "level_pb2.py"):
        path = output_dir / module
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "import common_pb2 as common__pb2", "from . import common_pb2 as common__pb2"
        )
        text = text.replace(
            "import scene_pb2 as scene__pb2", "from . import scene_pb2 as scene__pb2"
        )
        path.write_text(text, encoding="utf-8")


def generate() -> None:
    _generate(OUTPUT_DIR)


def check_reproducible() -> None:
    with tempfile.TemporaryDirectory(prefix="expra-proto-") as directory:
        output_dir = Path(directory)
        _generate(output_dir)
        expected = sorted(path.relative_to(output_dir) for path in output_dir.rglob("*.py"))
        actual = sorted(path.relative_to(OUTPUT_DIR) for path in OUTPUT_DIR.rglob("*.py"))
        if expected != actual:
            raise SystemExit(
                f"generated file set differs: expected {expected}, checked-in {actual}"
            )
        for relative in expected:
            if (output_dir / relative).read_bytes() != (OUTPUT_DIR / relative).read_bytes():
                raise SystemExit(f"generated binding is stale: {relative}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify checked-in bindings")
    arguments = parser.parse_args()
    check_reproducible() if arguments.check else generate()
