"""KiCad IPC action: TraceForge Signal Timing Monitor (xSignal timing through series parts).

Tools > External Plugins > TraceForge: Signal Timing Monitor opens a window that refreshes once
per second while you route and tune. It reads chain definitions from xsignals.json (project root
or docs/design/).
"""

from __future__ import annotations

import os

from kipy import KiCad

from signal_path_analyzer.kicad_adapter import chain_items, highlight
from signal_path_analyzer.monitor_web import serve
from signal_path_analyzer.session import Session


def main() -> int:
    board = KiCad().get_board()
    session = Session.open(board)
    if not session.config:
        print("TraceForge Signal Timing Monitor: no xsignals.json in the project root or "
              "docs/design/.")
        return 1

    def chain_of(group: str, name: str):
        g = session.config.group(group)
        return next(c for c in g.chains if c.name == name)

    def hl_chain(group: str, name: str) -> int:
        c = chain_of(group, name)
        return highlight(board, chain_items(board, c.nets, c.series))

    def hl_group(group: str) -> int:
        g = session.config.group(group)
        nets = [n for c in g.chains for n in c.nets]
        refs = [r for c in g.chains for r in c.series]
        return highlight(board, chain_items(board, nets, refs))

    def write(results) -> str:
        path = session.write_drc_targets(results)
        return f"targets written to {path.name}; run DRC or re-open Board Setup to reload rules"

    callbacks = (session.evaluate, hl_chain, hl_group, board.clear_selection, write)
    if os.environ.get("TRACEFORGE_UI") == "tk":  # optional desktop window (needs tkinter)
        from signal_path_analyzer.monitor_ui import MonitorWindow

        MonitorWindow(*callbacks).run()
    else:  # default: local web dashboard, standard library only (KiCad's Python has no tkinter)
        serve(*callbacks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
