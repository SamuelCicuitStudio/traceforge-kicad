"""KiCad IPC action entry point."""

from __future__ import annotations

import os
from pathlib import Path

from kipy import KiCad

from signal_path_analyzer import analyze_tracks
from signal_path_analyzer.kicad_adapter import collect_track_samples
from signal_path_analyzer.report import write_csv


def main() -> int:
    kicad = KiCad()
    board = kicad.get_board()
    board_name = Path(board.document.board_filename)
    project_directory = Path(board.document.project.path)
    output = project_directory / f"{board_name.stem}.signal-paths.csv"

    summaries = analyze_tracks(collect_track_samples(board))
    write_csv(output, summaries)
    print(
        f"TraceForge Export Signal Paths: wrote {len(summaries)} nets to {os.fspath(output)}. "
        "Delay is blank until a KiCad tuning profile is imported."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

