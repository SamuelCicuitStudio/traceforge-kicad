"""Read-only preview and undoable removal of proven redundant copper."""
import hashlib
import json
import secrets
from pathlib import Path

import pcbnew

from .trace_cleanup import analyze

_preview = None


def snapshot(board, net=''):
    ownership = Path(board.GetFileName()).with_suffix('.traceforge-fanout.json')
    managed = set()
    if ownership.exists():
        try:
            store = json.loads(ownership.read_text(encoding='utf-8'))
            managed = {key for record in store['records'].values()
                       for key in record['items']}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('Fanout ownership metadata could not be read. Preserve it '
                             'and resolve the error before cleanup.') from exc
    rows = []
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA) or (net and item.GetNetname() != net):
            continue
        start, end = item.GetStart(), item.GetEnd()
        arc = isinstance(item, pcbnew.PCB_ARC)
        mid = item.GetMid() if arc else None
        rows.append(dict(id=item.m_Uuid.AsString(), kind='arc' if arc else 'track',
                         name=item.GetNetname(), net=item.GetNetCode(),
                         layer=pcbnew.LayerName(item.GetLayer()), width=item.GetWidth(),
                         start=[start.x, start.y], end=[end.x, end.y],
                         mid=[mid.x, mid.y] if mid else None,
                         mask=[item.HasSolderMask(), item.GetLocalSolderMaskMargin()],
                         protected=bool(item.IsLocked() or item.GetParentGroup() or
                                        item.m_Uuid.AsString() in managed),
                         length_mm=item.GetLength() / 1e6))
        if len(rows) > 30000:
            raise ValueError('Cleanup previews support up to 30,000 tracks/arcs. '
                             'Enter an individual net name to narrow the scan.')
    rows.sort(key=lambda row: row['id'])
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return rows, digest


def validate(board, payload):
    if not _preview or payload.get('token') != _preview['token'] or (
            board.GetFileName() != _preview['board']):
        raise ValueError('Scan this board again before reviewing/removing tracks.')
    _, digest = snapshot(board, _preview['net'])
    if digest != _preview['digest']:
        raise ValueError('Tracks changed after the preview. Scan again; nothing was removed.')
    identities = set(payload.get('ids', []))
    allowed = {row['id'] for row in _preview['redundant'] + _preview['dangling']}
    if not identities or not identities <= allowed:
        raise ValueError('Choose tracks from the current cleanup preview.')
    return identities


def dispatch(board, operation, payload):
    global _preview
    if operation == 'cleanup_scan':
        net = str(payload.get('net', '')).strip()
        names = {n.GetNetname() for n in board.GetNetsByNetcode().values()}
        if net and net not in names:
            raise ValueError('Net name was not found in this board. Use the exact net name.')
        rows, digest = snapshot(board, net)
        analysis = analyze(rows)
        redundant = {row['id'] for row in analysis['redundant']}
        by_id = {item.m_Uuid.AsString(): item for item in board.GetTracks()}
        board.BuildConnectivity()
        connectivity = board.GetConnectivity()
        dangling = []
        for row in rows:
            if row['protected'] or row['net'] <= 0 or row['id'] in redundant:
                continue
            if connectivity.TestTrackEndpointDangling(by_id[row['id']], False):
                dangling.append(dict(id=row['id'], net=row['name'], layer=row['layer'],
                                     length_mm=row['length_mm'], keep=[],
                                     reason='Dangling endpoint: review before removal'))
        _preview = dict(analysis, dangling=dangling, token=secrets.token_hex(16), net=net,
                        board=board.GetFileName(), digest=digest, scanned=len(rows))
        return _preview
    if operation != 'cleanup_remove':
        raise ValueError('Unknown trace cleanup operation.')
    identities = validate(board, payload)
    from .stitching_native import transaction

    def remove(live):
        # Validate a second time inside the native undo wrapper before any deletion.
        validate(live, payload)
        items = [item for item in live.GetTracks() if item.m_Uuid.AsString() in identities]
        if len(items) != len(identities):
            raise ValueError('Preview tracks are no longer present. Scan again.')
        dangling_ids = {row['id'] for row in _preview['dangling']}
        live.BuildConnectivity()
        connectivity = live.GetConnectivity()
        for item in items:
            if item.m_Uuid.AsString() in dangling_ids and not (
                    connectivity.TestTrackEndpointDangling(item, False)):
                raise ValueError('A reviewed dangling track is now connected. Scan again.')
        for item in items:
            live.RemoveNative(item)
        live.BuildConnectivity()
        pcbnew.Refresh()
        return dict(removed=len(items))
    result = transaction(board, remove)
    _preview = None
    return result
