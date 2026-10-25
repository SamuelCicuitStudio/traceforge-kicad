"""Native pcbnew action: open the TraceForge panel (one toolbar button for every TraceForge tool).

If the panel is already open it is brought to the front instead of opening a second one.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import time
import traceback
from pathlib import Path

from signal_path_analyzer import analyze_tracks
from signal_path_analyzer.chains import selection_paths
from signal_path_analyzer.model import TrackSample
from signal_path_analyzer.report import write_csv
from signal_path_analyzer.session import Session
from signal_path_analyzer.single_instance import PORT, try_activate_existing


def build_tools(session: Session):
    from signal_path_analyzer.hub_ui import Tools

    native = session.native

    def select_paths(nets, refs):
        return native.call('highlight', nets=list(nets), refs=list(refs), zoom=True)

    def zoom():
        return "zoomed to selection" if native.call('zoom') else "nothing to zoom"

    # always read session.config: the Chain Editor replaces it while the panel is open
    def hl_chain(group: str, name: str) -> int:
        nets, refs = selection_paths(session.config.group(group), name)
        return select_paths(nets, refs)

    def hl_group(group: str) -> int:
        g = session.config.group(group)
        return select_paths([n for c in g.chains for n in c.nets],
                            [r for c in g.chains for r in c.series])

    def hl_selection(whole_group: bool) -> str:
        selection = native.call('selection')
        if not selection:
            return "select a track, via, pad or series part in KiCad first"
        item = selection[0]
        nets, refs, chain = session.resolve_chain(net=item.get('net'), ref=item.get('ref'))
        if not nets:
            return "the selected item is not part of a signal chain"
        if whole_group and chain is not None:
            return f"{chain.group}: highlighted {hl_group(chain.group)} items"
        count = (hl_chain(chain.group, chain.name) if chain is not None else
                 select_paths(nets, refs))
        label = f"{chain.group} {chain.name}" if chain else "auto-detected chain"
        return f"{label}: highlighted {count} items ({', '.join(refs) or 'no series part'})"

    def write(results) -> str:
        if session.config is None:
            return "no signal chains to write"
        if session.config.auto:
            return ("groups are auto-detected (driver side and limits unknown): open Chain editor, "
                    "review and Apply & save, then write DRC targets")
        return f"DRC targets written to {session.write_drc_targets(results).name}"

    def export() -> str:
        out = session.project_dir / f"{Path(session.board_file).stem}.signal-paths.csv"
        geometry = native.snapshot(list(native.call('netclasses')))
        samples = [TrackSample(n, seg.layer, seg.length_mm)
                   for n, geo in geometry.items() for seg in geo.tracks]
        summaries = analyze_tracks(samples)
        write_csv(out, summaries)
        return f"exported {len(summaries)} nets to {out.name}"

    def save() -> str:
        if session.config is None:
            return "no signal chains to save"
        return f"saved {session.save_config().name}; edit stub side, skew and limits, then reopen"

    def source() -> str:
        if session.config is None:
            return "nothing"
        backend = 'pcbnew native board access'
        label = "auto-detected chains (open Chain editor to review)" if session.config.auto else (
            session.config_file.name if session.config_file else "config")
        return f'{label} - {backend}'

    def edit(parent) -> str:
        from signal_path_analyzer.chain_editor import edit_chains
        from signal_path_analyzer.endpoint_service import EndpointService

        def apply(cfg) -> str:
            path = session.save_config(cfg)
            return f"saved {len(cfg.groups)} groups to {path.name}"

        def refs():
            return [i['ref'] for i in native.call('selection') if 'ref' in i]

        return edit_chains(parent, session.config, session.find_between, refs, apply,
                           detect_selected=EndpointService(session).detect)

    clear = lambda: native.call('clear')  # noqa: E731
    return Tools(session.evaluate, hl_chain, hl_group, hl_selection, clear, write,
                 export, save, source, edit, zoom)


def _log_to_file() -> None:
    """KiCad runs plugins without a console: keep a log with full tracebacks and fatal errors."""

    log_dir = Path(os.environ.get("APPDATA", Path.home())) / "TraceForge"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream = open(log_dir / "traceforge.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    stream.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} ---\n")
    sys.stdout = sys.stderr = stream
    faulthandler.enable(stream)
    logging.basicConfig(level=logging.INFO, stream=stream,
                        format="%(asctime)s %(levelname)s %(message)s", force=True)


def main() -> int:
    if try_activate_existing(PORT):
        return 0
    _log_to_file()
    try:
        from signal_path_analyzer import hub_ui
        from signal_path_analyzer.endpoint_service import EndpointService

        session = Session.open()
        hub_ui.run(build_tools(session), single_instance_port=PORT, stitching=session.native.call,
                   endpoints=EndpointService(session))
        print("panel closed normally")
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
