"""Native BGA pad-to-via breakout, with reviewed preview and undoable placement."""
from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from collections import Counter
from pathlib import Path

import pcbnew

from .fanout import candidates, fit_guidance, grid_info, matches, validate, world
from .fanout_escape import edge_paths, paired_net
from .stitching_native import fits, outline, point_mm, refill, transaction, uid

_preview = None


def store_path(board):
    return Path(board.GetFileName()).with_suffix('.traceforge-fanout.json')


def load_store(board):
    path = store_path(board)
    if not path.exists():
        return dict(version=1, records={})
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('records'), dict):
        raise ValueError('Unrecognized fanout ownership metadata; preserve the file for recovery.')
    return data


def snapshot(item):
    if isinstance(item, pcbnew.PCB_VIA):
        return dict(kind='via', net=item.GetNetname(), position=point_mm(item.GetPosition()),
                    diameter=item.GetWidth(pcbnew.F_Cu), drill=item.GetDrillValue(),
                    via_type=item.GetViaType(), top=item.TopLayer(), bottom=item.BottomLayer())
    return dict(kind='track', net=item.GetNetname(), start=point_mm(item.GetStart()),
                end=point_mm(item.GetEnd()), width=item.GetWidth(), layer=item.GetLayer())


def managed(board, footprint):
    store = load_store(board)
    live = {uid(t): t for t in board.GetTracks()}
    owned, changed = {}, set()
    for record in store['records'].values():
        if record['footprint'] != footprint:
            continue
        for identity, previous in record['items'].items():
            item = live.get(identity)
            if item is None:
                continue
            if (isinstance(item, (pcbnew.PCB_TRACK, pcbnew.PCB_VIA)) and
                    not isinstance(item, pcbnew.PCB_ARC) and not item.IsLocked() and
                    snapshot(item) == previous):
                owned[identity] = item
            else:
                changed.add(identity)
    return list(owned.values()), len(changed)


def journal(board, footprint, items, values):
    store = load_store(board)
    store['records'][str(uuid.uuid4())] = dict(footprint=footprint, settings=values,
                                               items={uid(t): snapshot(t) for t in items})
    path = store_path(board)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(store, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def selected_footprint(board, identity=None):
    if identity:
        fp = next((fp for fp in board.GetFootprints() if uid(fp) == identity), None)
        if fp is None:
            raise ValueError('The selected footprint was deleted. Select it again.')
        return fp
    selected = {}
    for item in pcbnew.GetCurrentSelection():
        fp = item if isinstance(item, pcbnew.FOOTPRINT) else item.GetParentFootprint()
        if fp:
            selected[uid(fp)] = fp
    if len(selected) != 1:
        raise ValueError('Select one BGA footprint or its pads in PCB Editor, '
                         'then Analyze selection.')
    return next(iter(selected.values()))


def analyze(board, identity=None):
    fp = selected_footprint(board, identity)
    pads = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.GetNumber()]
    if len(pads) > 1600:
        raise ValueError('This initial fanout supports at most 1,600 array pads.')
    data = [dict(id=uid(p), number=p.GetNumber(), net=p.GetNetname(),
                 local=point_mm(p.GetFPRelativePosition()), position=point_mm(p.GetPosition()),
                 size=point_mm(p.GetSize())) for p in pads]
    grid = grid_info(data)
    ds = board.GetDesignSettings()
    active = ds.GetViaSizeIndex()
    if not 0 <= active < len(ds.m_ViasDimensionsList):
        active = 0
    layer = pcbnew.B_Cu if fp.IsFlipped() else pcbnew.F_Cu
    items, changed = managed(board, uid(fp))
    net_rules = {}
    for pad in data:
        if pad['net'] and pad['net'] not in net_rules:
            nc = ds.m_NetSettings.GetEffectiveNetClass(pad['net'])
            net_rules[pad['net']] = dict(width=nc.GetTrackWidth() / 1e6,
                                         clearance=nc.GetClearance() / 1e6,
                                         diameter=nc.GetViaDiameter() / 1e6,
                                         drill=nc.GetViaDrill() / 1e6)
    names = {net.GetNetname() for net in board.GetNetsByNetcode().values()}
    return dict(id=uid(fp), reference=fp.GetReference(), pads=data, grid=grid,
                managed_items=len(items), modified_items=changed,
                position=point_mm(fp.GetPosition()), angle=fp.GetOrientationDegrees(),
                layer=pcbnew.LayerName(layer),
                copper_layers=[pcbnew.LayerName(c) for c in board.GetEnabledLayers().CuStack()],
                net_rules=net_rules,
                paired_nets=sorted(n for n in net_rules if paired_net(n, names)),
                presets=[[v.m_Diameter / 1e6, v.m_Drill / 1e6]
                         for v in ds.m_ViasDimensionsList], active=active,
                defaults=dict(diameter=ds.GetCurrentViaSize() / 1e6,
                              drill=ds.GetCurrentViaDrill() / 1e6,
                              width=max(ds.m_TrackMinWidth, .15e6) / 1e6,
                              clearance=ds.m_MinClearance / 1e6),
                limits=dict(diameter=ds.m_ViasMinSize / 1e6,
                            drill=ds.m_MinThroughDrill / 1e6,
                            annulus=ds.m_ViasMinAnnularWidth / 1e6,
                            width=ds.m_TrackMinWidth / 1e6,
                            clearance=ds.m_MinClearance / 1e6))


def mmvec(point):
    return pcbnew.VECTOR2I(round(point[0] * 1e6), round(point[1] * 1e6))


def clear_escape_route(route, layer, width, gap, edge, board_poly, zones,
                       obstacles, reserved, reserved_routes, ds, net):
    """Check every proposed segment against copper, holes, zones and board edges."""
    segments = []
    for start, finish in zip(route, route[1:]):
        a, b = mmvec(start), mmvec(finish)
        if a == b:
            continue
        shape = pcbnew.SHAPE_SEGMENT(a, b, round(width * 1e6))
        limit = round(width * 5e5 + edge)
        if not fits(board_poly, a, limit) or not fits(board_poly, b, limit):
            return None
        if any(ring.CSegment(k).Distance(pcbnew.SEG(a, b)) < limit
               for i in range(board_poly.OutlineCount())
               for ring in [board_poly.Outline(i)] +
               [board_poly.Hole(i, j) for j in range(board_poly.HoleCount(i))]
               for k in range(ring.SegmentCount())):
            return None
        bbox = shape.BBox()
        for zone in zones:
            if zone.GetIsRuleArea():
                if zone.GetDoNotAllowTracks() and zone.IsOnLayer(layer) and (
                        zone.Outline().Collide(shape)):
                    return None
            elif zone.GetNetname() != net and zone.IsOnLayer(layer):
                if zone.NeedRefill() or not zone.IsFilled():
                    raise ValueError('Refill copper zones before previewing BGA escape.')
                if zone.GetFilledPolysList(layer).Collide(shape, gap):
                    return None
        for _, box, shapes, other_gap, hole in obstacles:
            clearance = max(gap, other_gap, ds.m_HoleClearance)
            if (box.GetRight() + clearance < bbox.GetX() or
                    box.GetX() - clearance > bbox.GetRight() or
                    box.GetBottom() + clearance < bbox.GetY() or
                    box.GetY() - clearance > bbox.GetBottom()):
                continue
            if shapes.get(layer) and shapes[layer].Collide(shape, clearance):
                return None
            if hole and pcbnew.SHAPE.Collide(hole, shape, ds.m_HoleClearance):
                return None
        for old_circle, _, old_gap, old_drill in reserved:
            if (pcbnew.SHAPE.Collide(old_circle, shape, max(gap, old_gap)) or
                    pcbnew.SHAPE.Collide(old_drill, shape, ds.m_HoleClearance)):
                return None
        for old_segment, old_gap in reserved_routes:
            if pcbnew.SHAPE.Collide(old_segment, shape, max(gap, old_gap)):
                return None
        segments.append(shape)
    return segments or None


def plan(board, request):
    started = time.monotonic()
    data = analyze(board, request['footprint'])
    values = dict(request['settings'])
    ds = board.GetDesignSettings()
    preset = values.get('preset', 'custom')
    if preset not in ('custom', 'netclass'):
        index = data['active'] if preset == 'active' else int(preset)
        if not 0 <= index < len(ds.m_ViasDimensionsList):
            raise ValueError('The board preset changed. Analyze selection again.')
        if index:
            v = ds.m_ViasDimensionsList[index]
            values.update(diameter=v.m_Diameter / 1e6, drill=v.m_Drill / 1e6)
        else:
            # Resolve per-net sizes below; these values describe the preview's initial form.
            values.update(diameter=ds.GetCurrentViaSize() / 1e6,
                          drill=ds.GetCurrentViaDrill() / 1e6)
    values = validate(values)
    escape_layer = None
    if values['mode'] == 'auto-escape':
        if 'escape_layer' not in values:
            values['escape_layer'] = ('B.Cu' if data['layer'] == 'F.Cu' else 'F.Cu')
        escape_layer = next((c for c in board.GetEnabledLayers().CuStack()
                             if pcbnew.LayerName(c) == values['escape_layer']), None)
        if escape_layer is None or values['escape_layer'] == data['layer']:
            raise ValueError('Choose an enabled copper escape layer opposite the BGA pads.')
        eligible = [p for p in data['pads'] if p['net'] and
                    p['net'] not in data['paired_nets'] and
                    matches(p['net'], values.get('include', '*'), values.get('exclude', '')) and
                    matches(p['number'], values.get('pads', '*'))]
        if len(eligible) > 256:
            raise ValueError('Auto escape is limited to 256 selected pads per preview. '
                             'Filter nets or pad numbers to run another batch.')
    if len({p['number'] for p in data['pads']}) != len(data['pads']):
        raise ValueError('Duplicate pad numbers are not supported for BGA fanout.')
    if values['width'] * 1e6 < ds.m_TrackMinWidth:
        raise ValueError('Track width is below the board manufacturing minimum.')
    edge = max(values['edge'] * 1e6, ds.m_CopperEdgeClearance)
    board_poly = outline(board)
    layer = pcbnew.B_Cu if data['layer'] == 'B.Cu' else pcbnew.F_Cu
    copper_layers = list(board.GetEnabledLayers().CuStack())
    fp = selected_footprint(board, data['id'])
    pads = {uid(p): p for p in fp.Pads()}
    # Bound the initial implementation: broad-phase bounding boxes prune exact native
    # shape collision tests, including existing tracks/vias and all footprint pads.
    items = list(board.GetTracks()) + list(board.Drawings())
    for other in board.GetFootprints():
        items.extend(other.Pads())
        items.extend(other.GraphicalItems())
    obstacles = []
    for item in items:
        active = [copper for copper in copper_layers if item.IsOnLayer(copper)]
        hole = (item.GetEffectiveHoleShape()
                if isinstance(item, (pcbnew.PAD, pcbnew.PCB_VIA)) else None)
        if not active and not hole:
            continue
        box = item.GetBoundingBox()
        clearance = ds.m_MinClearance
        if isinstance(item, pcbnew.BOARD_CONNECTED_ITEM):
            clearance = max(clearance, ds.m_NetSettings.GetEffectiveNetClass(
                item.GetNetname()).GetClearance())
        shapes = {}
        if isinstance(item, (pcbnew.PAD, pcbnew.PCB_TRACK, pcbnew.PCB_SHAPE)):
            shapes = {copper: item.GetEffectiveShape(copper) for copper in active}
        else:
            shape = pcbnew.SHAPE_POLY_SET()
            shape.NewOutline()
            for x, y in ((box.GetX(), box.GetY()), (box.GetRight(), box.GetY()),
                         (box.GetRight(), box.GetBottom()), (box.GetX(), box.GetBottom())):
                shape.Append(x, y)
            shapes = dict.fromkeys(active, shape)
        obstacles.append((uid(item), box, shapes, clearance, hole))
    zones = list(board.Zones())
    accepted, skipped, rejected, reserved = [], [], [], []
    breakout_only, already_routed, reserved_routes = [], [], []
    grid = data['grid']
    # Inner balls first, with deterministic ordering and outward-preferred sites.
    ordered = sorted(data['pads'], key=lambda p: (
        abs(p['local'][0] - grid['center'][0]) + abs(p['local'][1] - grid['center'][1]),
        p['number']))
    for pad in ordered:
        if time.monotonic() - started > 15:
            raise ValueError('Fanout preview exceeded its time budget; filter fewer nets/pads.')
        net = pad['net']
        reason = None
        if not net or net.startswith('unconnected-'):
            reason = 'unconnected pad'
        elif values['mode'] == 'auto-escape' and net in data['paired_nets']:
            reason = 'differential pair: use a coupled escape method'
        elif not matches(net, values.get('include', '*'), values.get('exclude', '')):
            reason = 'net filter'
        elif not matches(pad['number'], values.get('pads', '*')):
            reason = 'pad filter'
        if reason:
            skipped.append(dict(pad=pad['number'], position=pad['position'], reason=reason))
            continue
        live_pad = pads[pad['id']]
        # Do not duplicate existing routed stubs; zone-only contact does not imply a stub.
        connected = board.GetConnectivity()
        if (connected.GetConnectedTracks(live_pad) or
            any(isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() == net and
                t.GetPosition() == live_pad.GetPosition() for t in board.GetTracks())):
            destination = already_routed if values['mode'] == 'auto-escape' else skipped
            destination.append(dict(pad=pad['number'], position=pad['position'],
                                    reason='already routed; existing escape not verified'))
            continue
        nc = ds.m_NetSettings.GetEffectiveNetClass(net)
        diameter, drill = values['diameter'], values['drill']
        if preset == 'netclass' or (preset == 'active' and data['active'] == 0):
            diameter, drill = nc.GetViaDiameter() / 1e6, nc.GetViaDrill() / 1e6
        if (diameter * 1e6 < ds.m_ViasMinSize or drill * 1e6 < ds.m_MinThroughDrill or
                (diameter - drill) * 5e5 < ds.m_ViasMinAnnularWidth):
            raise ValueError(f'Via dimensions for net {net} violate '
                             'board diameter/drill/annulus limits.')
        width = max(values['width'], nc.GetTrackWidth() / 1e6) if values.get(
            'netclass_width', True) else values['width']
        gap = round(max(values['clearance'] * 1e6, ds.m_MinClearance, nc.GetClearance()))
        pad_start = mmvec(pad['position'])
        locations = ([pad['local']] if values.get('mode') == 'via-in-pad' else
                     candidates(pad, grid, values['offset_x'], values['offset_y']))
        failures = []
        fallback = None
        for location in locations:
            end = mmvec(world(location, data['position'], data['angle']))
            radius = round(diameter * 5e5)
            circle = pcbnew.SHAPE_CIRCLE(end, radius)
            drill_circle = pcbnew.SHAPE_CIRCLE(end, round(drill * 5e5))
            segment = pcbnew.SHAPE_SEGMENT(pad_start, end, round(width * 1e6))
            why = None
            if not fits(board_poly, end, radius + edge):
                why = 'board edge / cutout'
            elif not fits(board_poly, pad_start, round(width * 5e5 + edge)):
                why = 'track edge / cutout'
            # Test the entire thick segment against every boundary, including holes.
            elif any(ring.CSegment(k).Distance(pcbnew.SEG(pad_start, end)) < width * 5e5 + edge
                     for i in range(board_poly.OutlineCount())
                     for ring in [board_poly.Outline(i)] + [board_poly.Hole(i, j)
                                 for j in range(board_poly.HoleCount(i))]
                     for k in range(ring.SegmentCount())):
                why = 'track edge / cutout'
            for zone in zones:
                if why:
                    break
                if zone.GetIsRuleArea():
                    if ((zone.GetDoNotAllowVias() and zone.Outline().Collide(circle)) or
                        (zone.GetDoNotAllowTracks() and zone.IsOnLayer(layer) and
                         zone.Outline().Collide(segment))):
                        why = 'keepout'
                elif zone.GetNetname() != net:
                    if zone.NeedRefill() or not zone.IsFilled():
                        raise ValueError('Refill copper zones in KiCad before previewing fanout.')
                    for copper in zone.GetLayerSet().CuStack():
                        poly = zone.GetFilledPolysList(copper)
                        if (poly.Collide(circle, gap) or
                                (copper == layer and poly.Collide(segment, gap))):
                            why = 'other-net zone copper'
                            break
            bbox = segment.BBox()
            for identity, box, shapes, other_gap, hole in obstacles:
                if why:
                    break
                clearance = max(gap, other_gap)
                margin = radius + clearance + max(ds.m_HoleClearance, ds.m_HoleToHoleMin)
                if (box.GetRight() + margin < min(bbox.GetX(), end.x) or
                    box.GetX() - margin > max(bbox.GetRight(), end.x) or
                    box.GetBottom() + margin < min(bbox.GetY(), end.y) or
                    box.GetY() - margin > max(bbox.GetBottom(), end.y)):
                    continue
                if identity == pad['id']:
                    if values.get('mode') != 'via-in-pad' and any(
                            shape and shape.Collide(circle, 0) for shape in shapes.values()):
                        why = 'dogbone overlaps source pad'
                    continue
                if (any(shape and (shape.Collide(circle, clearance) or
                                    shape.Collide(drill_circle, ds.m_HoleClearance))
                        for shape in shapes.values()) or
                    (shapes.get(layer) and shapes[layer].Collide(segment, clearance))):
                    why = 'pad / track / via clearance'
                elif hole and (pcbnew.SHAPE.Collide(hole, circle, max(
                                ds.m_HoleClearance, ds.m_HoleToHoleMin)) or
                               pcbnew.SHAPE.Collide(hole, segment, ds.m_HoleClearance)):
                    why = 'hole clearance'
            for old_circle, old_segment, old_gap, old_drill in reserved:
                if why:
                    break
                clearance = max(gap, old_gap)
                if (pcbnew.SHAPE.Collide(old_circle, circle, max(clearance, ds.m_HoleToHoleMin)) or
                    pcbnew.SHAPE.Collide(old_circle, segment, clearance) or
                    pcbnew.SHAPE.Collide(old_segment, circle, clearance) or
                    pcbnew.SHAPE.Collide(old_segment, segment, clearance) or
                    pcbnew.SHAPE.Collide(old_drill, drill_circle, ds.m_HoleToHoleMin) or
                    pcbnew.SHAPE.Collide(old_drill, segment, ds.m_HoleClearance) or
                    pcbnew.SHAPE.Collide(old_segment, drill_circle, ds.m_HoleClearance)):
                    why = 'fanout-to-fanout clearance'
            if why:
                failures.append(why)
                continue
            row = dict(pad=pad['number'], id=pad['id'], net=net,
                                 start=pad['position'], end=point_mm(end),
                                 diameter=diameter, drill=drill, width=width)
            route_shapes = []
            if escape_layer is not None:
                fallback = row
                for local_path in edge_paths(location, grid):
                    route = [world(p, data['position'], data['angle']) for p in local_path]
                    route_shapes = clear_escape_route(
                        route, escape_layer, width, gap, edge, board_poly, zones,
                        obstacles, reserved, reserved_routes, ds, net)
                    if route_shapes:
                        row.update(route=route, edge_endpoint=route[-1],
                                   escape_layer=values['escape_layer'], status='escaped')
                        break
                if not route_shapes:
                    failures.append('no clear route to BGA pad-field edge')
                    continue
            else:
                row['status'] = 'breakout only'
            accepted.append(row)
            reserved.append((circle, segment, gap, drill_circle))
            reserved_routes.extend((shape, gap) for shape in route_shapes)
            break
        else:
            if fallback is not None:
                breakout_only.append(dict(fallback, reason='Breakout fits, but no clear '
                                          'route reaches the BGA pad-field edge.'))
            else:
                rejected.append(dict(pad=pad['number'], position=pad['position'],
                                     reason=Counter(failures).most_common(1)[0][0]))
    return dict(footprint=data['id'], settings=values, data=data, accepted=accepted,
                skipped=skipped, rejected=rejected, breakout_only=breakout_only,
                already_routed=already_routed,
                reasons=dict(Counter(p['reason'] for p in
                                     rejected + skipped + breakout_only)))


def suggest(board, request):
    """Evaluate a bounded set of manufacturable candidates; never place or change rules."""
    started = time.monotonic()
    data = analyze(board, request['footprint'])
    values = validate(request['settings'])
    ds = board.GetDesignSettings()
    if data['managed_items']:
        raise ValueError('Remove the generated fanout before evaluating replacement settings. '
                         'This command will not remove it automatically.')
    minimum_drill = ds.m_MinThroughDrill / 1e6
    minimum_via = max(ds.m_ViasMinSize / 1e6,
                      minimum_drill + 2 * ds.m_ViasMinAnnularWidth / 1e6)
    sizes = {(values['diameter'], values['drill']), (minimum_via, minimum_drill)}
    sizes.update(tuple(v) for v in data['presets'][1:])
    sizes.add((data['defaults']['diameter'], data['defaults']['drill']))
    widths = {values['width'], ds.m_TrackMinWidth / 1e6}
    grid = data['grid']
    maximum = fit_guidance(data, values)['via_gap_limit']
    options = []
    for diameter, drill in sizes:
        if (diameter < minimum_via or drill < minimum_drill or
            (diameter - drill) / 2 + 1e-9 < ds.m_ViasMinAnnularWidth / 1e6):
            continue
        for width in widths:
            if width < ds.m_TrackMinWidth / 1e6 or width <= 0:
                continue
            options.append(dict(values, diameter=diameter, drill=drill,
                                width=width, preset='custom'))
    # Prefer larger manufacturable vias/widths; actual native geometry determines fitness.
    options.sort(key=lambda v: (v['drill'], v['diameter'], v['width']), reverse=True)
    # Ensure the minimum-size option is tested even with many board presets.
    selected = options[:3]
    if options and options[-1] not in selected:
        selected.append(options[-1])
    results = []
    for candidate in selected:
        if time.monotonic() - started > 25:
            break
        result = plan(board, dict(footprint=data['id'], settings=candidate))
        results.append(dict(settings=candidate, accepted=len(result['accepted']),
                            blocked=len(result['rejected']) + len(result['breakout_only']),
                            breakout_only=len(result['breakout_only']),
                            skipped=len(result['skipped']),
                            reasons=result['reasons']))
    results.sort(key=lambda r: (r['accepted'], -r['blocked'], r['settings']['drill'],
                                r['settings']['width']), reverse=True)
    return dict(candidates=results, checked=len(results),
                pitch_x=grid['pitch_x'], pitch_y=grid['pitch_y'],
                gap_via_limit_mm=max(0, maximum),
                note='Through-via suggestions only. Each candidate was checked against current '
                     'geometry; preview again after choosing one. No microvia/HDI inference.')


def dispatch(board, operation, payload):
    global _preview
    if operation == 'fanout_analyze':
        return analyze(board, payload.get('footprint'))
    if operation == 'fanout_remove':
        _preview = None
        identity = payload['footprint']
        selected_footprint(board, identity)
        items, changed = managed(board, identity)
        if not items:
            raise ValueError('No unchanged, unlocked generated fanout items remain. '
                             'Untracked/manual routing is preserved.')
        if len(items) > payload.get('expected_count', 0):
            raise ValueError('The generated fanout changed. '
                             'Analyze selection again before removing.')

        def remove(live):
            for item in items:
                live.RemoveNative(item)
            refill(live)
            return dict(removed=len(items), preserved=changed)

        return transaction(board, remove)
    if operation == 'fanout_suggest':
        _preview = None
        return suggest(board, payload)
    if operation == 'fanout_preview':
        _preview = None
        result = plan(board, payload)
        token = secrets.token_hex(16)
        _preview = (board.GetFileName(), token, result)
        return dict(result, token=token)
    if operation != 'fanout_apply':
        raise ValueError('Unsupported fanout command.')
    if _preview is None or _preview[:2] != (board.GetFileName(), payload.get('token')):
        raise ValueError('Preview expired. Preview again before applying fanout.')
    old = _preview[2]
    _preview = None
    current = plan(board, old)
    if any(current[k] != old[k] for k in ('settings', 'data', 'accepted')):
        raise ValueError('Board, footprint or settings changed. Preview fanout again.')
    if not current['accepted']:
        raise ValueError('No accepted fanout routes to apply.')

    created, source_pairs, escape_pairs = [], [], []
    layer = pcbnew.B_Cu if current['data']['layer'] == 'B.Cu' else pcbnew.F_Cu
    fp = selected_footprint(board, current['footprint'])
    pads = {uid(p): p for p in fp.Pads()}
    for row in current['accepted']:
        via = pcbnew.PCB_VIA(board)
        via.SetViaType(pcbnew.VIATYPE_THROUGH)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetPosition(mmvec(row['end']))
        via.SetWidth(round(row['diameter'] * 1e6))
        via.SetDrill(round(row['drill'] * 1e6))
        via.SetNetCode(board.FindNet(row['net']).GetNetCode())
        via.SetIsFree(True)
        created.append(via)
        if mmvec(row['start']) != mmvec(row['end']):
            track = pcbnew.PCB_TRACK(board)
            track.SetLayer(layer)
            track.SetStart(mmvec(row['start']))
            track.SetEnd(mmvec(row['end']))
            track.SetWidth(round(row['width'] * 1e6))
            track.SetNetCode(via.GetNetCode())
            created.append(track)
        route_tracks = []
        if row.get('route'):
            route_layer = next(c for c in board.GetEnabledLayers().CuStack()
                               if pcbnew.LayerName(c) == row['escape_layer'])
            for start, finish in zip(row['route'], row['route'][1:]):
                route_track = pcbnew.PCB_TRACK(board)
                route_track.SetLayer(route_layer)
                route_track.SetStart(mmvec(start))
                route_track.SetEnd(mmvec(finish))
                route_track.SetWidth(round(row['width'] * 1e6))
                route_track.SetNetCode(via.GetNetCode())
                created.append(route_track)
                route_tracks.append(route_track)
            escape_pairs.append((via, route_tracks, mmvec(row['edge_endpoint'])))
        source_pairs.append((pads[row['id']], via))

    def apply(live):
        for item in created:
            live.Add(item)
        refill(live)
        conn = live.GetConnectivity()
        if any(not any(uid(item) == uid(via) for item in conn.GetConnectedItems(pad))
               for pad, via in source_pairs):
            raise RuntimeError('Fanout connectivity validation failed after placement.')
        for via, route_tracks, endpoint in escape_pairs:
            if not route_tracks or route_tracks[0].GetStart() != via.GetPosition() or (
                    route_tracks[-1].GetEnd() != endpoint) or any(
                    previous.GetEnd() != following.GetStart()
                    for previous, following in zip(route_tracks, route_tracks[1:])):
                raise RuntimeError('BGA edge route lost continuity before commit.')
            connected = {uid(item) for item in conn.GetConnectedItems(via)}
            if uid(route_tracks[0]) not in connected:
                raise RuntimeError('BGA edge route is not connected to its via.')
        journal(live, current['footprint'], created, current['settings'])
        return dict(pads=len(current['accepted']), items=len(created),
                    escaped=len(escape_pairs), rejected=len(current['rejected']))

    return transaction(board, apply)
