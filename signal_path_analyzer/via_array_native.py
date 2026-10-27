"""Preview and undoably arrange existing, zone-connected PCB vias."""
from __future__ import annotations

import secrets

import pcbnew

from .stitching_native import inset_centers, outline, transaction, uid
from .via_array import arrange

_preview = None


def _selected(board):
    live = {uid(v): v for v in board.GetTracks() if isinstance(v, pcbnew.PCB_VIA)}
    chosen = {uid(v): live[uid(v)] for v in pcbnew.GetCurrentSelection()
              if isinstance(v, pcbnew.PCB_VIA) and uid(v) in live and v.IsSelected()}
    if not chosen:
        raise ValueError('Select the vias in PCB Editor, then click Read selection.')
    if len(chosen) > 64:
        raise ValueError('Select no more than 64 vias at once.')
    if any(v.IsLocked() for v in chosen.values()):
        raise ValueError('Unlock the selected vias before arranging them.')
    kinds = {(v.GetNetCode(), v.GetViaType(), v.TopLayer(), v.BottomLayer(),
              v.GetWidth(pcbnew.F_Cu), v.GetDrillValue()) for v in chosen.values()}
    if len(kinds) != 1:
        raise ValueError('Select vias with the same net, size, drill, and layer pair.')
    return chosen


def _snapshot(chosen):
    return tuple(sorted((identity, v.GetPosition().x, v.GetPosition().y)
                        for identity, v in chosen.items()))


def _near(item, point, radius):
    box = item.GetBoundingBox()
    return not (box.GetRight() < point.x - radius or box.GetX() > point.x + radius or
                box.GetBottom() < point.y - radius or box.GetY() > point.y + radius)


def _shape_touch(item, point, radius, layers, clearance=0):
    circle = pcbnew.SHAPE_CIRCLE(point, radius)
    for layer in layers:
        if item.IsOnLayer(layer):
            shape = item.GetEffectiveShape(layer)
            if shape and shape.Collide(circle, clearance):
                return True
    return False


def _check(board, chosen, layout):
    """Conservatively reject detachment, copper collisions and zone loss."""
    vias = list(chosen.values())
    via = vias[0]
    ds = board.GetDesignSettings()
    nc = ds.m_NetSettings.GetEffectiveNetClass(via.GetNetname())
    clearance = max(nc.GetClearance(), ds.m_HoleClearance, ds.m_HoleToHoleMin)
    diameter = via.GetWidth(pcbnew.F_Cu)
    radius = (diameter + 1) // 2
    copper_layers = [layer for layer in board.GetEnabledLayers().CuStack()
                     if via.IsOnLayer(layer)]
    region = inset_centers(outline(board), radius + ds.m_CopperEdgeClearance)
    zones = []
    for zone in board.Zones():
        relevant = [layer for layer in copper_layers if zone.IsOnLayer(layer)]
        if not relevant:
            continue
        if zone.GetIsRuleArea():
            if zone.GetDoNotAllowVias():
                zones.append((None, zone.Outline(), 'via keepout'))
            continue
        if not zone.IsFilled() or zone.NeedRefill():
            raise ValueError('Refill zones in PCB Editor, then preview the via array again.')
        for layer in relevant:
            zones.append((layer, zone.GetFilledPolysList(layer),
                          'same' if zone.GetNetCode() == via.GetNetCode() else 'foreign'))
    obstacles = list(board.GetTracks())
    for fp in board.GetFootprints():
        obstacles.extend(fp.Pads())
    obstacles.extend(item for item in board.Drawings()
                     if isinstance(item, pcbnew.BOARD_CONNECTED_ITEM) and
                     any(item.IsOnLayer(layer) for layer in copper_layers))
    selected_ids = set(chosen)
    old_layers = {}
    for identity, item in chosen.items():
        point = item.GetPosition()
        old_layers[identity] = {layer for layer, poly, kind in zones
                                if kind == 'same' and
                                poly.Contains(point, -1, 0, True)}
        for other in obstacles:
            if uid(other) in selected_ids or isinstance(other, pcbnew.PCB_VIA):
                continue
            if not _near(other, point, radius):
                continue
            if _shape_touch(other, point, radius, copper_layers):
                if other.GetNetCode() != item.GetNetCode():
                    raise ValueError('A selected via touches other-net copper.')
                old_layers[identity].update(
                    layer for layer in copper_layers
                    if other.IsOnLayer(layer) and
                    _shape_touch(other, point, radius, [layer]))
    issues = []
    moved = [row for row in layout['moves'] if row['old'] != row['new']]
    for row in moved:
        point = pcbnew.VECTOR2I(*row['new'])
        reason = None
        if not region.Contains(point, -1, 0, True):
            reason = 'board edge or cutout'
        elif any(poly.Collide(pcbnew.SHAPE_CIRCLE(point, radius))
                 for layer, poly, kind in zones if kind == 'via keepout'):
            reason = 'via keepout'
        else:
            same_layers = {layer for layer, poly, kind in zones
                           if kind == 'same' and poly.Contains(point, -1, 0, True)}
            for other in obstacles:
                if (uid(other) in selected_ids or
                        other.GetNetCode() != via.GetNetCode() or
                        isinstance(other, pcbnew.PCB_VIA) or
                        not _near(other, point, radius)):
                    continue
                same_layers.update(layer for layer in copper_layers
                                   if other.IsOnLayer(layer) and
                                   _shape_touch(other, point, radius, [layer]))
            if not old_layers[row['uuid']].issubset(same_layers):
                reason = 'same-net copper contact would be lost on a layer'
        if reason is None:
            for item in obstacles:
                if isinstance(item, pcbnew.PCB_VIA) and item.GetNetCode() == via.GetNetCode():
                    if uid(item) not in selected_ids:
                        other_point = item.GetPosition()
                        drill_gap = (via.GetDrillValue() + item.GetDrillValue()) / 2
                        drill_gap += ds.m_HoleToHoleMin
                        if ((point.x - other_point.x) ** 2 +
                                (point.y - other_point.y) ** 2 < drill_gap ** 2):
                            reason = 'via drill-to-drill clearance'
                            break
                    continue
                if (uid(item) in selected_ids or
                        (item.GetNetCode() == via.GetNetCode() and
                         not isinstance(item, pcbnew.PCB_VIA)) or
                        not _near(item, point, radius + clearance)):
                    continue
                if _shape_touch(item, point, radius, copper_layers, clearance):
                    reason = 'pad, track or via clearance'
                    break
        if reason:
            issues.append((row['uuid'], reason))
    # All selected vias have the same net. Their annular copper may approach or
    # overlap; only the physical drill-to-drill rule applies between them.
    centers = [row['new'] for row in layout['moves']]
    required = via.GetDrillValue() + ds.m_HoleToHoleMin
    for i, a in enumerate(centers):
        for b in centers[i + 1:]:
            if (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 < required ** 2:
                issues.append((layout['moves'][i]['uuid'], 'via drill-to-drill clearance'))
                break
    return issues, old_layers


def dispatch(board, operation, payload):
    global _preview
    if operation == 'via_array_selection':
        chosen = _selected(board)
        points = _snapshot(chosen)
        suggested = arrange(points, 'auto', None)
        return dict(count=len(points), net=next(iter(chosen.values())).GetNetname(),
                    rows=suggested['rows'], columns=suggested['columns'],
                    bounds=[min(p[1] for p in points) / 1e6,
                            min(p[2] for p in points) / 1e6,
                            max(p[1] for p in points) / 1e6,
                            max(p[2] for p in points) / 1e6])
    if operation == 'via_array_preview':
        chosen = _selected(board)
        layout = arrange(_snapshot(chosen), payload['fixed_axis'], payload['fixed_count'])
        issues, old_layers = _check(board, chosen, layout)
        token = secrets.token_hex(12)
        _preview = dict(board=board.GetFileName(), selected=_snapshot(chosen),
                        fixed_axis=payload['fixed_axis'], fixed_count=payload['fixed_count'],
                        layout=layout, issues=issues, old_layers=old_layers, token=token)
        return dict(token=token, count=len(chosen), net=next(iter(chosen.values())).GetNetname(),
                    rows=layout['rows'], columns=layout['columns'],
                    inferred=layout.get('inferred', False),
                    diameter_mm=next(iter(chosen.values())).GetWidth(pcbnew.F_Cu) / 1e6,
                    pitch_x_mm=layout['pitch_x_nm'] / 1e6,
                    pitch_y_mm=layout['pitch_y_nm'] / 1e6,
                    bounds_mm=[v / 1e6 for v in layout['bounds']],
                    moves=[dict(uuid=row['uuid'], old=[v / 1e6 for v in row['old']],
                                new=[v / 1e6 for v in row['new']]) for row in layout['moves']],
                    issues=issues, accepted=not issues)
    if operation != 'via_array_apply':
        raise ValueError('Unsupported via array operation.')
    saved = _preview
    _preview = None  # A preview is single-use, even if board validation fails.
    if not saved or saved['token'] != payload.get('token') or saved['board'] != board.GetFileName():
        raise ValueError('Preview expired. Read the selection and preview again.')
    chosen = _selected(board)
    if _snapshot(chosen) != saved['selected']:
        raise ValueError('The selected vias moved or changed. Preview again.')
    layout = arrange(_snapshot(chosen), saved['fixed_axis'], saved['fixed_count'])
    issues, old_layers = _check(board, chosen, layout)
    if layout != saved['layout'] or issues or issues != saved['issues']:
        raise ValueError('The board or clearance result changed. Preview again.')
    moves = [row for row in layout['moves'] if row['old'] != row['new']]
    if not moves:
        return dict(moved=0, message='Selected vias already occupy this grid.')

    def apply(live):
        current = {uid(v): v for v in live.GetTracks() if isinstance(v, pcbnew.PCB_VIA)}
        for row in moves:
            current[row['uuid']].SetPosition(pcbnew.VECTOR2I(*row['new']))
        # Leave zone refill to the user, as with an ordinary interactive move.
        live.BuildConnectivity()
        conn = live.GetConnectivity()
        if any(not all(conn.IsConnectedOnLayer(current[row['uuid']], layer)
                       for layer in old_layers[row['uuid']]) for row in moves):
            raise RuntimeError('Copper contact changed after moving vias.')
        pcbnew.Refresh()
        return dict(moved=len(moves),
                    message=f'Arranged {len(moves)} vias; Undo restores them.')

    return transaction(board, apply)
