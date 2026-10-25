"""Read-only preview and undoable removal of proven redundant copper."""
import hashlib
import json
import secrets
from pathlib import Path

import pcbnew

from .trace_cleanup import analyze

_preview = None


def overview(board):
    """Cheap tab summary; do not build connectivity or analyze copper."""
    copper_ids = [pcbnew.F_Cu, *(i for i in range(4, 32, 2)), pcbnew.B_Cu]
    enabled = [layer for layer in copper_ids if board.IsLayerEnabled(layer)]
    layers = [pcbnew.LayerName(layer) for layer in enabled]
    tracks = {layer: 0 for layer in layers}
    for item in board.GetTracks():
        if not isinstance(item, pcbnew.PCB_VIA):
            layer = pcbnew.LayerName(item.GetLayer())
            if layer in tracks:
                tracks[layer] += 1
    return dict(board=board.GetFileName(), layers=layers, layer_tracks=tracks,
                layer_visibility={pcbnew.LayerName(layer): bool(board.IsLayerVisible(layer))
                                  for layer in enabled})


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
    allowed = {row['id'] for row in _preview['redundant'] + _preview['dangling'] +
               _preview['fusions']}
    if not identities or not identities <= allowed:
        raise ValueError('Choose tracks from the current cleanup preview.')
    return identities


def focus_ids(board, payload):
    identities = validate(board, payload)
    expanded = set()
    for item in _preview['fusions']:
        if item['id'] in identities:
            expanded.update(item['ids'])
    return expanded | {identity for identity in identities if not identity.startswith('fuse:')}


def dispatch(board, operation, payload):
    global _preview
    if operation == 'cleanup_info':
        return overview(board)
    if operation == 'cleanup_scan':
        net = str(payload.get('net', '')).strip()
        names = {n.GetNetname() for n in board.GetNetsByNetcode().values()}
        if net and net not in names:
            raise ValueError('Net name was not found in this board. Use the exact net name.')
        rows, digest = snapshot(board, net)
        info = overview(board)
        layers = info['layers']
        visibility = info['layer_visibility']
        analysis = analyze(rows)
        for group in analysis['fusions']:
            group['id'] = 'fuse:' + hashlib.sha256(
                '|'.join(group['ids']).encode()).hexdigest()[:20]
            group['reason'] = f"Fuse {len(group['ids'])} overlapping tracks"
            start, end = group['start'], group['end']
            group['length_mm'] = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** .5 / 1e6
        fused = {identity for group in analysis['fusions'] for identity in group['ids']}
        redundant = {row['id'] for row in analysis['redundant']}
        by_id = {item.m_Uuid.AsString(): item for item in board.GetTracks()}
        board.BuildConnectivity()
        connectivity = board.GetConnectivity()
        dangling = []
        for row in rows:
            if row['protected'] or row['net'] <= 0 or row['id'] in redundant | fused:
                continue
            if connectivity.TestTrackEndpointDangling(by_id[row['id']], False):
                dangling.append(dict(id=row['id'], net=row['name'], layer=row['layer'],
                                     length_mm=row['length_mm'], keep=[],
                                     reason='Dangling endpoint: review before removal'))
        _preview = dict(analysis, dangling=dangling, token=secrets.token_hex(16), net=net,
                        board=board.GetFileName(), digest=digest, scanned=len(rows),
                        overview=info,
                        layers=layers, layer_visibility=visibility,
                        layer_tracks={layer: sum(row['layer'] == layer for row in rows)
                                      for layer in layers})
        return _preview
    if operation != 'cleanup_remove':
        raise ValueError('Unknown trace cleanup operation.')
    identities = validate(board, payload)
    from .stitching_native import transaction

    def remove(live):
        # Validate a second time inside the native undo wrapper before any deletion.
        validate(live, payload)
        groups = [group for group in _preview['fusions'] if group['id'] in identities]
        ordinary = {identity for identity in identities if not identity.startswith('fuse:')}
        members = {identity for group in groups for identity in group['ids']}
        chosen = ordinary | members
        if len(chosen) != len(ordinary) + sum(len(group['ids']) for group in groups):
            raise ValueError('Overlapping cleanup choices require a new preview.')
        live_items = {item.m_Uuid.AsString(): item for item in live.GetTracks()}
        items = [live_items[identity] for identity in chosen if identity in live_items]
        if len(items) != len(chosen):
            raise ValueError('Preview tracks are no longer present. Scan again.')
        dangling_ids = {row['id'] for row in _preview['dangling']}
        live.BuildConnectivity()
        connectivity = live.GetConnectivity()
        for item in items:
            if item.m_Uuid.AsString() in dangling_ids and not (
                    connectivity.TestTrackEndpointDangling(item, False)):
                raise ValueError('A reviewed dangling track is now connected. Scan again.')
        replacements = []
        for group in groups:
            source = live_items[group['ids'][0]]
            replacement = pcbnew.PCB_TRACK(live)
            replacement.SetNet(source.GetNet())
            replacement.SetLayer(source.GetLayer())
            replacement.SetWidth(source.GetWidth())
            replacement.SetStart(pcbnew.VECTOR2I(*group['start']))
            replacement.SetEnd(pcbnew.VECTOR2I(*group['end']))
            replacement.SetHasSolderMask(source.HasSolderMask())
            replacement.SetLocalSolderMaskMargin(source.GetLocalSolderMaskMargin())
            replacements.append(replacement)
        for item in items:
            live.RemoveNative(item)
        for item in replacements:
            live.Add(item)
        live.BuildConnectivity()
        pcbnew.Refresh()
        return dict(removed=len(items), fused=len(groups), added=len(replacements))
    result = transaction(board, remove)
    _preview = None
    return result
