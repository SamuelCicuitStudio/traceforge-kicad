"""Read-only live copper-cluster scan. No DRC, board save, copper edit or zone fill."""
import math
import time
from collections import defaultdict

import pcbnew as k

from .unrouted_core import links_between, row_identity

_CACHE = {}


def identity(item):
    return item.m_Uuid.AsString()


def copper_items(board):
    return [*board.GetTracks(), *(pad for fp in board.GetFootprints() for pad in fp.Pads()
                                 if pad.GetNetCode() > 0 and pad.IsOnCopperLayer())]


def anchors(item):
    if isinstance(item, k.PAD):
        label = item.GetParentFootprint().GetReference()+'.'+item.GetNumber()
        points = [item.GetPosition()]
    elif isinstance(item, k.PCB_VIA):
        label = 'Via'
        points = [item.GetPosition()]
    else:
        label = 'Track'
        points = [item.GetStart(), item.GetEnd()]
    return [dict(id=identity(item), label=label,
                 position=[k.ToMM(p.x), k.ToMM(p.y)]) for p in points]


def scan(board, payload=None):
    started = time.monotonic()
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    conn.RecalculateRatsnest()
    by_net = defaultdict(dict)
    for item in copper_items(board):
        if item.GetNetCode() > 0:
            by_net[item.GetNetCode()][identity(item)] = item
    rows = []
    for _code, items in sorted(by_net.items()):
        if time.monotonic()-started > 100:
            raise RuntimeError('Unrouted scan exceeded 100 seconds. '
                               'No partial result was published.')
        remaining = set(items)
        clusters = []
        has_copper = any(not isinstance(item, k.PAD) for item in items.values())
        while remaining:
            key = min(remaining)
            seed = items[key]
            connected = list(conn.GetConnectedItems(seed))
            # Do not union through a zone PARENT object: separate fill islands share
            # that parent but are correctly separated by native cluster searches.
            ids = {identity(item) for item in connected if identity(item) in items}
            ids.add(key)
            remaining.difference_update(ids)
            points = [a for item_id in sorted(ids) for a in anchors(items[item_id])]
            clusters.append(points)
            has_copper |= any(isinstance(item, k.ZONE) for item in connected)
        if len(clusters) < 2:
            continue
        if len(clusters) > 2000:
            raise RuntimeError('A net has over 2000 disconnected clusters; '
                               'scan is too large for this tool.')
        net = next(iter(items.values())).GetNetname()
        netclass = next(iter(items.values())).GetNetClassName()
        for row in links_between(clusters):
            row.update(net=net, netclass=netclass, clusters=len(clusters),
                       status='Remaining gap' if has_copper else 'Unrouted net')
            row['id'] = row_identity(net, row['a'], row['b'])
            rows.append(row)
    rows.sort(key=lambda r: (r['gap_mm'], r['net'], r['id']))
    _CACHE[str(board.GetFileName())] = {row['id']: row for row in rows}
    return dict(rows=rows, native_airwires=conn.GetUnconnectedCount(False),
                nets=len({row['net'] for row in rows}),
                note='Live pad/track clusters; nearest-anchor links may differ from the drawn '
                     'ratsnest tree. Filled zones use their current fill; no refill was run.')


def focus(board, payload):
    row = _CACHE.get(str(board.GetFileName()), {}).get(payload.get('id'))
    if row is None:
        raise ValueError('This connection snapshot is stale. Refresh Unrouted.')
    items = {identity(item): item for item in copper_items(board)}
    if any(row[end]['id'] not in items for end in ('a', 'b')):
        return dict(resolved=True, message='Endpoint changed or removed; refresh the list.')
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    first, second = items[row['a']['id']], items[row['b']['id']]
    if identity(second) in {identity(item) for item in conn.GetConnectedItems(first)}:
        return dict(resolved=True, message='This gap is now connected; refreshing the list.')
    ends = []
    for end in ('a', 'b'):
        candidates = anchors(items[row[end]['id']])
        ends.append(min(candidates, key=lambda a: math.dist(a['position'], row[end]['position'])))
    return dict(resolved=False, ids=[a['id'] for a in ends],
                net=row['net'], points=[a['position'] for a in ends])
