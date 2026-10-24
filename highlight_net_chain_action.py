"""KiCad IPC action: highlight the whole net chain of the selected item.

Select any track, via or pad of a signal, or a series resistor/choke, then run
Tools > External Plugins > TraceForge: Highlight Signal Chain. All copper of every net in the
chain plus the series parts become selected, so the signal stands out end to end.
"""

from __future__ import annotations

from kipy import KiCad
from kipy.board_types import FootprintInstance

from signal_path_analyzer.kicad_adapter import chain_items, highlight
from signal_path_analyzer.session import Session

TAG = "TraceForge Highlight Signal Chain"


def main() -> int:
    board = KiCad().get_board()
    session = Session.open(board)
    selection = list(board.get_selection())
    if not selection:
        print(f"{TAG}: select a track, via, pad or series part first.")
        return 1
    item = selection[0]
    if isinstance(item, FootprintInstance):
        nets, refs, chain = session.resolve_chain(ref=item.reference_field.text.value)
    else:
        net = getattr(getattr(item, "net", None), "name", None)
        nets, refs, chain = session.resolve_chain(net=net)
    if not nets:
        print(f"{TAG}: the selected item is not part of a net chain.")
        return 1
    count = highlight(board, chain_items(board, nets, refs))
    label = f"{chain.group} {chain.name}" if chain else "auto-detected chain"
    via = ", ".join(refs) or "no series part"
    print(f"{TAG}: {label}: {len(nets)} nets via {via} ({count} items selected).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
