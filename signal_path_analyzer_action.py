"""Native pcbnew action: export signal-path track summaries."""
from __future__ import annotations

from signal_path_analyzer import analyze_tracks
from signal_path_analyzer.model import TrackSample
from signal_path_analyzer.report import write_csv
from signal_path_analyzer.session import Session


def main() -> int:
    session = Session.open()
    geometry = session.native.snapshot(list(session.native.call('netclasses')))
    samples = [TrackSample(n, seg.layer, seg.length_mm)
               for n, geo in geometry.items() for seg in geo.tracks]
    output = session.board_file.with_suffix('.signal-paths.csv')
    summaries = analyze_tracks(samples)
    write_csv(output, summaries)
    print(f'TraceForge: exported {len(summaries)} nets to {output}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
