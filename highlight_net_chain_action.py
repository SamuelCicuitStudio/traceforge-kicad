"""Native pcbnew action: highlight the chain of the selected PCB item."""
from __future__ import annotations

from signal_path_analyzer.chains import selection_paths
from signal_path_analyzer.session import Session


def main() -> int:
    session = Session.open()
    selection = session.native.call('selection')
    if not selection:
        print('TraceForge: select a track, via, pad or series part first.')
        return 1
    item = selection[0]
    nets, refs, chain = session.resolve_chain(net=item.get('net'), ref=item.get('ref'))
    if not nets:
        print('TraceForge: the selected item is not part of a signal chain.')
        return 1
    if chain is not None:
        nets, refs = selection_paths(session.config.group(chain.group), chain.name)
    count = session.native.call('highlight', nets=list(nets), refs=list(refs), zoom=True)
    print(f'TraceForge: highlighted {count} items through native pcbnew access.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
