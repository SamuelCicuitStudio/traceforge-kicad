"""Preview and undoable whole-board fillets with persistent selective restore."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections import Counter, defaultdict
from pathlib import Path

import pcbnew

from .stitching_native import transaction
from .trace_fillet import MIN_RADIUS_IU, plan, refit

_preview = None


def _uid(item):
    return item.m_Uuid.AsString()


def _xy(point):
    return [point.x, point.y]


def _vec(point):
    return pcbnew.VECTOR2I(*point)


def _store_path(board):
    return Path(board.GetFileName()).with_suffix('.traceforge-fillets.json')


def _load(board):
    path = _store_path(board)
    if not path.exists():
        return {'version': 1, 'records': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('records'), list):
        raise ValueError('TraceForge fillet history has an unsupported format.')
    return data


def _save(board, data):
    path = _store_path(board)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def _rows(board, store):
    managed = {identity for record in store['records']
               for identity in record['tracks']}
    rows, protected = [], set()
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA):
            point = tuple(_xy(item.GetPosition()))
            for layer in range(0, 64):
                if item.IsOnLayer(layer):
                    protected.add((layer, point))
        elif isinstance(item, pcbnew.PCB_ARC):
            for point in (item.GetStart(), item.GetEnd()):
                protected.add((item.GetLayer(), tuple(_xy(point))))
        elif isinstance(item, pcbnew.PCB_TRACK):
            rows.append(dict(id=_uid(item), start=_xy(item.GetStart()),
                             end=_xy(item.GetEnd()), layer=item.GetLayer(),
                             net=item.GetNetCode(), name=item.GetNetname(),
                             width=item.GetWidth(),
                             protected=bool(item.IsLocked() or item.GetParentGroup() or
                                            _uid(item) in managed)))
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            point = tuple(_xy(pad.GetPosition()))
            for layer in range(0, 64):
                if pad.IsOnLayer(layer):
                    protected.add((layer, point))
    return rows, protected


def _fingerprint(rows, protected):
    data = [sorted(rows, key=lambda row: row['id']), sorted(protected)]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _track(board, source, start, end):
    item = pcbnew.PCB_TRACK(board)
    item.SetStart(_vec(start))
    item.SetEnd(_vec(end))
    item.SetLayer(source.GetLayer())
    item.SetWidth(source.GetWidth())
    item.SetNet(source.GetNet())
    item.SetHasSolderMask(source.HasSolderMask())
    item.SetLocalSolderMaskMargin(source.GetLocalSolderMaskMargin())
    return item


def _selected_ids():
    return {_uid(item) for item in pcbnew.GetCurrentSelection()
            if isinstance(item, (pcbnew.PCB_TRACK, pcbnew.PCB_ARC))}


def _signature(item):
    result = dict(start=_xy(item.GetStart()), end=_xy(item.GetEnd()),
                  width=item.GetWidth(), layer=item.GetLayer(), net=item.GetNetCode())
    if isinstance(item, pcbnew.PCB_ARC):
        result['mid'] = _xy(item.GetMid())
    return result


def _clearance_filter(board, candidates, adaptive=True):
    """Skip arcs colliding with other-net copper at the relevant item clearance.

    This is intentionally conservative. Filled zones and custom DRC rules still
    require a final KiCad DRC run after the edit.
    """
    cell = 2_000_000
    search_clearance = board.GetDesignSettings().GetBiggestClearanceValue()
    minimum = board.GetDesignSettings().m_MinClearance
    buckets = defaultdict(list)
    objects = list(board.GetTracks())
    by_id = {_uid(item): item for item in objects}
    for footprint in board.GetFootprints():
        objects.extend(footprint.Pads())
    copper_layers = [layer for layer in range(0, 64) if board.IsLayerEnabled(layer)
                     and (layer == pcbnew.F_Cu or layer == pcbnew.B_Cu or
                          4 <= layer <= 62 and layer % 2 == 0)]
    for item in objects:
        box = item.GetBoundingBox()
        for layer in copper_layers:
            if not item.IsOnLayer(layer):
                continue
            entry = (item.GetNetCode(), box, item,
                     max(minimum, item.GetOwnClearance(layer)))
            left, right = box.GetLeft() // cell, box.GetRight() // cell
            top, bottom = box.GetTop() // cell, box.GetBottom() // cell
            if (right - left + 1) * (bottom - top + 1) > 10000:
                continue
            for x in range(left, right + 1):
                for y in range(top, bottom + 1):
                    buckets[(layer, x, y)].append(entry)
    accepted, skipped = [], []
    proposed = defaultdict(list)
    def evaluate(corner):
        arc = pcbnew.PCB_ARC(board)
        arc.SetStart(_vec(corner['tangent'][0]))
        arc.SetMid(_vec(corner['mid']))
        arc.SetEnd(_vec(corner['tangent'][1]))
        arc.SetWidth(corner['width'])
        arc.SetLayer(corner['layer'])
        shape = arc.GetEffectiveShape(corner['layer'])
        own_clearance = max(minimum,
                            by_id[corner['ids'][0]].GetOwnClearance(corner['layer']))
        box = arc.GetBoundingBox().GetInflated(search_clearance)
        seen = set()
        conflict = False
        for x in range(box.GetLeft() // cell, box.GetRight() // cell + 1):
            for y in range(box.GetTop() // cell, box.GetBottom() // cell + 1):
                for net, obstacle, item, item_clearance in buckets.get(
                        (corner['layer'], x, y), ()):
                    key = id(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    if (net != corner['net'] and box.Intersects(obstacle) and
                            shape.Collide(item.GetEffectiveShape(corner['layer']),
                                          max(own_clearance, item_clearance))):
                        conflict = True
                        break
                if conflict:
                    break
            if conflict:
                break
        if not conflict:
            for x in range(box.GetLeft() // cell, box.GetRight() // cell + 1):
                for y in range(box.GetTop() // cell, box.GetBottom() // cell + 1):
                    if any(other_net != corner['net'] and box.Intersects(other_box) and
                           shape.Collide(other_shape,
                                         max(own_clearance, other_clearance))
                           for other_net, other_box, other_shape, other_clearance in
                           proposed.get((corner['layer'], x, y), ())):
                        conflict = True
                        break
                if conflict:
                    break
        return conflict, box, shape, own_clearance

    for corner in candidates:
        conflict, box, shape, own_clearance = evaluate(corner)
        if conflict and adaptive and corner['radius_iu'] > MIN_RADIUS_IU:
            upper = corner['radius_iu']
            # Moving the tangent points toward the vertex often clears nearby
            # copper. Keep the requested radius as the preferred maximum.
            for fraction in (0.8, 0.6, 0.4, 0.2, 0.1, 0.05):
                radius = max(MIN_RADIUS_IU, round(upper * fraction))
                trial = refit(corner, radius)
                trial_conflict, trial_box, trial_shape, trial_clearance = evaluate(trial)
                if not trial_conflict:
                    corner, conflict = trial, False
                    box, shape, own_clearance = trial_box, trial_shape, trial_clearance
                    break
                if radius == MIN_RADIUS_IU:
                    break
        if conflict:
            skipped.append({**corner, 'reason': 'Nearby copper on another net'})
        else:
            accepted.append(corner)
            for x in range(box.GetLeft() // cell, box.GetRight() // cell + 1):
                for y in range(box.GetTop() // cell, box.GetBottom() // cell + 1):
                    proposed[(corner['layer'], x, y)].append(
                        (corner['net'], box, shape, own_clearance))
    return accepted, skipped


def dispatch(board, operation, payload):
    global _preview
    if operation == 'fillet_preview':
        radius = float(payload.get('radius', 0))
        if not 0.05 <= radius <= 100:
            raise ValueError('Choose a radius from 0.05 to 100 mm.')
        store = _load(board)
        rows, protected = _rows(board, store)
        scope = payload.get('scope', 'all')
        if scope not in ('all', 'selected'):
            raise ValueError('Choose whole board or selected tracks.')
        selected = _selected_ids() if scope == 'selected' else None
        if scope == 'selected' and not selected:
            raise ValueError('Select straight tracks in PCB Editor first.')
        net = str(payload.get('net', '')).strip()
        if net:
            net_ids = {row['id'] for row in rows if row['name'] == net}
            if not net_ids:
                raise ValueError('No straight tracks found for this exact net name.')
            selected = net_ids if selected is None else selected & net_ids
        adaptive = bool(payload.get('adaptive', True))
        accepted, skipped = plan(rows, protected, radius * 1e6, selected, adaptive)
        accepted, nearby = _clearance_filter(board, accepted, adaptive)
        skipped.extend(nearby)
        _preview = dict(board=board.GetFileName(), radius=radius,
                        token=secrets.token_hex(16), digest=_fingerprint(rows, protected),
                        accepted=accepted, skipped=skipped)
        adjusted = sum(row['radius_iu'] < radius * 1e6 - 1 for row in accepted)
        return dict(token=_preview['token'], accepted=len(accepted),
                    skipped=len(skipped), existing=len(store['records']),
                    adjusted=adjusted,
                    reasons=dict(Counter(row['reason'] for row in skipped)),
                    examples=[{'net': row['nets'][0], 'layer': pcbnew.LayerName(row['layer']),
                               'point': [round(value / 1e6, 4) for value in row['point']],
                               'reason': row['reason']} for row in skipped[:80]])
    if operation == 'fillet_restore_list':
        store = _load(board)
        selected = _selected_ids()
        records = store['records']
        if payload.get('selected_only'):
            records = [record for record in records if record['arc'] in selected or
                       any(identity in selected for identity in record['tracks'])]
        return {'count': len(records), 'total': len(store['records']),
                'records': [{'id': record['arc'], 'net': record['net'],
                             'layer': pcbnew.LayerName(record['layer'])}
                            for record in records]}
    if operation == 'fillet_apply':
        if not _preview or payload.get('token') != _preview['token'] or \
                board.GetFileName() != _preview['board']:
            raise ValueError('Preview this board again before applying.')
        store = _load(board)
        rows, protected = _rows(board, store)
        if _fingerprint(rows, protected) != _preview['digest']:
            raise ValueError('Tracks changed after preview. Preview again.')
        if not _preview['accepted']:
            raise ValueError('No eligible corners at this radius.')
        corners = _preview['accepted']

        def apply(live):
            current = {item.m_Uuid.AsString(): item for item in live.GetTracks()}
            new_ends = {}
            for corner in corners:
                for identity, end, point in zip(corner['ids'], corner['ends'],
                                                corner['tangent']):
                    new_ends.setdefault(identity, {})[end] = point
            replacements = {}
            for identity, ends in new_ends.items():
                old = current[identity]
                replacement = _track(live, old,
                                     ends.get('start', _xy(old.GetStart())),
                                     ends.get('end', _xy(old.GetEnd())))
                replacements[identity] = replacement
            arcs = []
            for corner in corners:
                source = current[corner['ids'][0]]
                arc = pcbnew.PCB_ARC(live)
                arc.SetStart(_vec(corner['tangent'][0]))
                arc.SetMid(_vec(corner['mid']))
                arc.SetEnd(_vec(corner['tangent'][1]))
                arc.SetLayer(source.GetLayer())
                arc.SetWidth(source.GetWidth())
                arc.SetNet(source.GetNet())
                arc.SetHasSolderMask(source.HasSolderMask())
                arc.SetLocalSolderMaskMargin(source.GetLocalSolderMaskMargin())
                arcs.append(arc)
            for identity in replacements:
                live.RemoveNative(current[identity])
            for item in [*replacements.values(), *arcs]:
                live.Add(item)
            live.BuildConnectivity()
            pcbnew.Refresh()
            return {'replacements': {old: _uid(new) for old, new in replacements.items()},
                    'arcs': [_uid(arc) for arc in arcs]}

        result = transaction(board, apply)
        live_items = {_uid(item): item for item in board.GetTracks()}
        for corner, arc_id in zip(corners, result['arcs']):
            track_ids = [result['replacements'][identity] for identity in corner['ids']]
            store['records'].append(dict(arc=arc_id, net=corner['nets'][0],
                                         layer=corner['layer'], point=corner['point'],
                                         arc_shape=_signature(live_items[arc_id]),
                                         tracks=track_ids,
                                         track_shapes=[_signature(live_items[identity])
                                                       for identity in track_ids],
                                         ends=corner['ends'], tangent=corner['tangent']))
        skipped_count = len(_preview['skipped'])
        _save(board, store)
        _preview = None
        return {'added': len(corners), 'skipped': skipped_count}
    if operation != 'fillet_restore':
        raise ValueError('Unsupported trace fillet operation.')
    store = _load(board)
    scope = payload.get('scope', 'selected')
    if scope not in ('selected', 'all'):
        raise ValueError('Choose selected corners or all generated corners.')
    if scope == 'all':
        chosen = list(store['records'])
    else:
        selected = _selected_ids()
        if not selected:
            raise ValueError('Select a TraceForge fillet arc or adjacent track in PCB Editor.')
        chosen = [record for record in store['records'] if record['arc'] in selected or
                  any(identity in selected for identity in record['tracks'])]
    if not chosen:
        raise ValueError('No TraceForge fillets found for this restore scope.')
    current = {_uid(item): item for item in board.GetTracks()}
    for record in chosen:
        arc = current.get(record['arc'])
        if (not isinstance(arc, pcbnew.PCB_ARC) or arc.IsLocked() or
                _signature(arc) != record.get('arc_shape')):
            raise ValueError('A generated arc changed or was removed. Cannot safely restore.')
        for identity, expected in zip(record['tracks'], record['track_shapes']):
            item = current.get(identity)
            if (not isinstance(item, pcbnew.PCB_TRACK) or item.IsLocked() or
                    _signature(item) != expected):
                raise ValueError('An adjacent track changed. Cannot safely restore.')

    def restore(live):
        items = {_uid(item): item for item in live.GetTracks()}
        ends_by_id = {}
        for record in chosen:
            for identity, end in zip(record['tracks'], record['ends']):
                ends_by_id.setdefault(identity, {})[end] = record['point']
        replacements = {}
        for identity, ends in ends_by_id.items():
            old = items[identity]
            replacements[identity] = _track(live, old,
                                            ends.get('start', _xy(old.GetStart())),
                                            ends.get('end', _xy(old.GetEnd())))
        for record in chosen:
            live.RemoveNative(items[record['arc']])
        for identity in replacements:
            live.RemoveNative(items[identity])
        for item in replacements.values():
            live.Add(item)
        live.BuildConnectivity()
        pcbnew.Refresh()
        return {old: _uid(new) for old, new in replacements.items()}

    replacements = transaction(board, restore)
    removed = {record['arc'] for record in chosen}
    store['records'] = [record for record in store['records'] if record['arc'] not in removed]
    for record in store['records']:
        record['tracks'] = [replacements.get(identity, identity)
                            for identity in record['tracks']]
        record['track_shapes'] = [_signature(next(item for item in board.GetTracks()
                                                  if _uid(item) == identity))
                                  for identity in record['tracks']]
    _save(board, store)
    _preview = None
    return {'restored': len(chosen)}
