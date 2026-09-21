"""Keep importable application modules within the repository size budget."""

from __future__ import annotations

import io
import tokenize
import unittest
import warnings
from pathlib import Path

SOFT_LINE_LIMIT = 700
HARD_LINE_LIMIT = 900
SOURCE_ROOT = Path(__file__).parents[1] / "src" / "expra_engine"


def count_source_lines(source: str) -> int:
    """Count physical lines containing Python tokens other than comments."""
    counted_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in {
            tokenize.ENCODING,
            tokenize.ENDMARKER,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.NEWLINE,
            tokenize.NL,
            tokenize.COMMENT,
        }:
            continue
        counted_lines.update(range(token.start[0], token.end[0] + 1))
    return len(counted_lines)


class CodeSizeTests(unittest.TestCase):
    def test_python_modules_stay_below_hard_limit(self) -> None:
        oversized = []
        soft_overages = []
        for path in sorted(SOURCE_ROOT.rglob("*.py")):
            lines = count_source_lines(path.read_text(encoding="utf-8"))
            if lines > HARD_LINE_LIMIT:
                oversized.append(f"{path.relative_to(SOURCE_ROOT)}: {lines} lines")
            elif lines > SOFT_LINE_LIMIT:
                soft_overages.append(f"{path.relative_to(SOURCE_ROOT)}: {lines} lines")
        if soft_overages:
            warnings.warn(
                "module exceeds the 700-line soft threshold: " + ", ".join(soft_overages),
                stacklevel=1,
            )
        self.assertFalse(
            oversized,
            "modules over 900 lines require consolidation before further growth: "
            + ", ".join(oversized),
        )

    def test_source_line_count_excludes_comments_but_counts_code(self) -> None:
        source = """\
# module comment

value = (  # inline comment
    1
)
# trailing comment
text = "# not a comment"
"""

        self.assertEqual(count_source_lines(source), 4)


if __name__ == "__main__":
    unittest.main()
