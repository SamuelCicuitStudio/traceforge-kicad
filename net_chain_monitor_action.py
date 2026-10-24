"""Native pcbnew action: TraceForge Signal Timing Monitor (xSignal timing through series parts).

Tools > External Plugins > TraceForge: Signal Timing Monitor opens a window that refreshes once
per second while you route and tune. It reads chain definitions from xsignals.json (project root
or docs/design/).
"""

from __future__ import annotations

import os

from signal_path_analyzer.chains import selection_paths
from signal_path_analyzer.monitor_web import serve
from signal_path_analyzer.session import Session


def main() -> int:
    session = Session.open()
    if not session.config:
        print("TraceForge Signal Timing Monitor: no xsignals.json in the project root or "
              "docs/design/.")
        return 1

    def hl_chain(group: str, name: str) -> int:
        nets, refs = selection_paths(session.config.group(group), name)
        return session.native.call('highlight', nets=list(nets), refs=list(refs), zoom=True)

    def hl_group(group: str) -> int:
        g = session.config.group(group)
        return session.native.call('highlight', nets=[n for c in g.chains for n in c.nets],
                                   refs=[r for c in g.chains for r in c.series], zoom=True)

    def write(results) -> str:
        path = session.write_drc_targets(results)
        return f"targets written to {path.name}; run DRC or re-open Board Setup to reload rules"

    callbacks = (session.evaluate, hl_chain, hl_group, lambda: session.native.call('clear'), write)
    if os.environ.get("TRACEFORGE_UI") == "tk":  # optional desktop window (needs tkinter)
        from signal_path_analyzer.monitor_ui import MonitorWindow

        MonitorWindow(*callbacks).run()
    else:  # default: local web dashboard, standard library only (KiCad's Python has no tkinter)
        serve(*callbacks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
