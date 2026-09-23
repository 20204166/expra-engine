"""diagnostics_analyze: aggregate captured log records by stable signature.

``RenderDiagnostics`` (runtime/render_diagnostics.py) only dedups repeats
within a single live process and tracks no counts or timestamps at all --
confirmed by reading its full 35-line source. So this module does the actual
count/first/last/sample aggregation the spec's "511 repeated lines -> one
entry" example needs, over records ``render_snapshot``'s ``_RecordCapture``
handler already wrote to disk.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from . import artifacts


def aggregate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group by (logger, level, unformatted message template).

    The %-style template (before argument interpolation) is a natural
    signature: the same template means the same failure class even though
    the interpolated args (entity id, kind, ...) differ per occurrence.
    """

    groups: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
    for record in records:
        key = (record["logger"], record["level"], record["message_template"])
        group = groups.get(key)
        if group is None:
            group = {
                "signature": "|".join(key),
                "logger": record["logger"],
                "level": record["level"],
                "message_template": record["message_template"],
                "count": 0,
                "first_timestamp": record["timestamp"],
                "last_timestamp": record["timestamp"],
                "sample": record["formatted"],
            }
            groups[key] = group
        group["count"] += 1
        group["first_timestamp"] = min(group["first_timestamp"], record["timestamp"])
        group["last_timestamp"] = max(group["last_timestamp"], record["timestamp"])
    return list(groups.values())


def analyze_run(diagnostics_dir: Path, run_id: str) -> dict[str, Any]:
    records = artifacts.read_diagnostics_records(diagnostics_dir, run_id)
    failures = aggregate_records(records)
    return {
        "run_id": run_id,
        "raw_record_count": len(records),
        "unique_failures": len(failures),
        "failures": failures,
    }
