"""KiCad IPC action: open the TraceForge panel (one toolbar button for every TraceForge tool).

If the panel is already open it is brought to the front instead of opening a second one.
"""

from __future__ import annotations

from pathlib import Path

from kipy import KiCad
from kipy.board_types import FootprintInstance

from signal_path_analyzer import analyze_tracks
from signal_path_analyzer.kicad_adapter import chain_items, collect_track_samples, highlight
from signal_path_analyzer.report import write_csv
from signal_path_analyzer.session import Session
from signal_path_analyzer.single_instance import PORT, try_activate_existing


def build_tools(board, session: Session):
    from signal_path_analyzer.hub_ui import Tools

    config = session.config

    def chain_of(group: str, name: str):
        return next(c for c in config.group(group).chains if c.name == name)

    def hl_chain(group: str, name: str) -> int:
        c = chain_of(group, name)
        return highlight(board, chain_items(board, c.nets, c.series))

    def hl_group(group: str) -> int:
        g = config.group(group)
        return highlight(board, chain_items(board, [n for c in g.chains for n in c.nets],
                                            [r for c in g.chains for r in c.series]))

    def hl_selection(whole_group: bool) -> str:
        selection = list(board.get_selection())
        if not selection:
            return "select a track, via, pad or series part in KiCad first"
        item = selection[0]
        if isinstance(item, FootprintInstance):
            nets, refs, chain = session.resolve_chain(ref=item.reference_field.text.value)
        else:
            nets, refs, chain = session.resolve_chain(net=getattr(item.net, "name", None))
        if not nets:
            return "the selected item is not part of a signal chain"
        if whole_group and chain is not None:
            return f"{chain.group}: highlighted {hl_group(chain.group)} items"
        count = highlight(board, chain_items(board, nets, refs))
        label = f"{chain.group} {chain.name}" if chain else "auto-detected chain"
        return f"{label}: highlighted {count} items ({', '.join(refs) or 'no series part'})"

    def write(results) -> str:
        return f"DRC targets written to {session.write_drc_targets(results).name}"

    def export() -> str:
        out = session.project_dir / f"{Path(session.board_file).stem}.signal-paths.csv"
        summaries = analyze_tracks(collect_track_samples(board))
        write_csv(out, summaries)
        return f"exported {len(summaries)} nets to {out.name}"

    evaluate = session.evaluate if config else (lambda: [])
    return Tools(evaluate, hl_chain, hl_group, hl_selection, board.clear_selection, write, export)


def main() -> int:
    if try_activate_existing(PORT):
        return 0
    from signal_path_analyzer import hub_ui

    board = KiCad().get_board()
    session = Session.open(board)
    hub_ui.run(build_tools(board, session), single_instance_port=PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
