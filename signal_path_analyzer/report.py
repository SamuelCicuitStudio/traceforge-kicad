"""CSV reporting for signal-path analysis results."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from .model import NetSummary


def write_csv(path: Path, summaries: Iterable[NetSummary]) -> None:
    """Write summaries in deterministic net-name order."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("net_name", "track_count", "length_mm", "delay_ps", "layers"))
        for summary in sorted(summaries, key=lambda row: row.net_name):
            writer.writerow(
                (
                    summary.net_name,
                    summary.track_count,
                    f"{summary.length_mm:.6f}",
                    "" if summary.delay_ps is None else f"{summary.delay_ps:.6f}",
                    ";".join(summary.layers),
                )
            )

