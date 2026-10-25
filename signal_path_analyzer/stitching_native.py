"""Stitching operations executed exclusively on KiCad's GUI thread."""
from __future__ import annotations

import secrets
import time
import uuid
from collections import Counter, defaultdict

import pcbnew
import wx

from .stitching import grid, inside, load_store, polygon, save_store, settings

COMMIT_LABEL = 'TraceForge: Apply Stitching Changes'
PREFIX = 'TraceForge stitching: '
_pending = None
_preview = None


def uid(item):
    return item.m_Uuid.AsString()


def point_mm(point):
    return [point.x / 1e6, point.y / 1e6]


def contours(poly):
    result = []
    for i in range(poly.OutlineCount()):
        lines = [poly.Outline(i)] + [poly.Hole(i, j) for j in range(poly.HoleCount(i))]
        result.append([[point_mm(line.CPoint(j)) for j in range(line.PointCount())]
                       for line in lines])
    return result


def outline(board):
    poly = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(poly, False) or not poly.OutlineCount():
        raise ValueError('The board needs a valid closed Edge.Cuts outline.')
    return poly


def fits(poly, point, radius):
    if not poly.Contains(point):
        return False
    for i in range(poly.OutlineCount()):
        if poly.Outline(i).Distance(point, True) < radius:
            return False
        for j in range(poly.HoleCount(i)):
            if poly.Hole(i, j).Distance(point, True) < radius:
                return False
    return True


def region_item(board, identity):
    return next((item for item in list(board.Zones()) + list(board.Drawings())
                 if uid(item) == identity), None)


def item_region(board, item):
    if isinstance(item, pcbnew.ZONE) and not item.GetIsRuleArea():
        return dict(kind='zone', uuid=uid(item), net=item.GetNetname(),
                    points=contours(item.Outline())[0][0])
    if isinstance(item, pcbnew.PCB_SHAPE):
        if item.GetLayer() in board.GetEnabledLayers().CuStack():
            raise ValueError('Choose a rectangle/polygon on a non-copper drawing layer.')
        if item.GetShape() == pcbnew.SHAPE_T_RECT:
            a, b = point_mm(item.GetStart()), point_mm(item.GetEnd())
            points = [a, [b[0], a[1]], b, [a[0], b[1]]]
        elif item.GetShape() == pcbnew.SHAPE_T_POLY:
            poly = item.GetPolyShape()
            if poly.OutlineCount() != 1 or poly.HoleCount(0):
                raise ValueError('Select a single closed polygon without holes.')
            points = contours(poly)[0][0]
        else:
            raise ValueError('Select a copper zone, rectangle or closed polygon.')
        return dict(kind='shape', uuid=uid(item), points=polygon(points))
    raise ValueError('Select one copper zone, rectangle or polygon in PCB Editor.')


def catalog(board, store=None):
    store = store or load_store(board.GetFileName())
    live = {uid(v): v for v in board.GetTracks() if isinstance(v, pcbnew.PCB_VIA)}
    result = []
    for key, record in store['records'].items():
        owned = {k: live[k] for k in record['vias'] if k in live}
        if not owned:
            continue
        modified = sum(not unchanged(v, record['vias'][k], record['settings']['net'])
                       for k, v in owned.items())
        result.append(dict(id=key, name=record['name'],
                           net=next(iter(owned.values())).GetNetname(), count=len(owned),
                           status='Managed' if not modified else
                           f'{modified} manually edited vias will be preserved',
                           extra=0, record=record))
    return result


def scene(board):
    ds = board.GetDesignSettings()
    nets = {}
    for net in board.GetNetsByNetcode().values():
        if net.GetNetname():
            nc = ds.m_NetSettings.GetEffectiveNetClass(net.GetNetname())
            nets[net.GetNetname()] = [nc.GetViaDiameter() / 1e6, nc.GetViaDrill() / 1e6]
    selected = [item for item in pcbnew.GetCurrentSelection()
                if isinstance(item, (pcbnew.ZONE, pcbnew.PCB_SHAPE))]
    selection, selection_error = None, None
    if len(selected) == 1:
        try:
            selection = item_region(board, selected[0])
        except ValueError as exc:
            selection_error = str(exc)
    return dict(board=board.GetFileName(), outline=contours(outline(board)), nets=nets,
                presets=[[v.m_Diameter / 1e6, v.m_Drill / 1e6]
                         for v in ds.m_ViasDimensionsList], active_preset=ds.GetViaSizeIndex(),
                selected_region=selection, selection_error=selection_error,
                sets=catalog(board), last=load_store(board.GetFileName()).get('last', {}))


def resolve(board, values):
    values = dict(values)
    net = board.FindNet(values.get('net', ''))
    if net is None or not net.GetNetCode():
        raise ValueError('The chosen net no longer exists on this board.')
    ds = board.GetDesignSettings()
    source = values.get('size_source', 'board')
    if source not in ('board', 'netclass', 'custom') and not source.startswith('preset:'):
        raise ValueError('Choose a board preset, netclass or custom via size.')
    index = ds.GetViaSizeIndex() if source == 'board' else 0
    if source.startswith('preset:'):
        index = int(source.split(':')[1])
        if not 0 < index < len(ds.m_ViasDimensionsList):
            raise ValueError('The board via preset no longer exists.')
    if source != 'custom':
        if index:
            v = ds.m_ViasDimensionsList[index]
            values['diameter'], values['drill'] = v.m_Diameter / 1e6, v.m_Drill / 1e6
        else:
            nc = ds.m_NetSettings.GetEffectiveNetClass(net.GetNetname())
            values['diameter'], values['drill'] = nc.GetViaDiameter() / 1e6, nc.GetViaDrill() / 1e6
    values = settings(values)
    if (values['diameter'] * 1e6 < ds.m_ViasMinSize or
        values['drill'] * 1e6 < ds.m_MinThroughDrill or
        (values['diameter'] - values['drill']) * 5e5 < ds.m_ViasMinAnnularWidth):
        raise ValueError('Via dimensions violate board minimum diameter, drill or annular ring.')
    if min(values['pitch_x'], values['pitch_y']) * 1e6 < (
            values['diameter'] * 1e6 + ds.m_MinClearance):
        raise ValueError('Spacing would violate clearance between generated vias.')
    return values, net


def unchanged(via, old, net):
    now = [*point_mm(via.GetPosition()), via.GetWidth(pcbnew.F_Cu) / 1e6,
           via.GetDrillValue() / 1e6]
    return (via.GetNetname() == net and not via.IsLocked() and
            via.GetViaType() == pcbnew.VIATYPE_THROUGH and
            all(abs(via.GetWidth(layer) / 1e6 - old[2]) <= 1e-6
                for layer in via.GetBoard().GetEnabledLayers().CuStack()) and
            all(abs(a - b) <= 1e-6 for a, b in zip(old, now)))


def ownership(board, identities, store, select=False):
    live = {uid(v): v for v in board.GetTracks() if isinstance(v, pcbnew.PCB_VIA)}
    chosen = []
    for key in set(identities):
        record = store['records'].get(key)
        if record is None:
            raise ValueError('Stitching ownership is missing; refresh the set list.')
        vias = [live[k] for k, old in record['vias'].items() if k in live and
                (select or unchanged(live[k], old, record['settings']['net']))]
        chosen.append((key, vias))
    return chosen


def plan(board, request):
    started = time.monotonic()
    values, net = resolve(board, request['settings'])
    region = dict(request['region'])
    if region['kind'] in ('zone', 'shape'):
        item = region_item(board, region['uuid'])
        if item is None:
            raise ValueError('The selected region was deleted; select it again.')
        region = item_region(board, item)
        if region.get('net', values['net']) != values['net']:
            raise ValueError('The region zone belongs to another net.')
    board_poly = outline(board)
    rings = contours(board_poly)
    points = ([p for ring in rings for p in ring[0]] if region['kind'] == 'board'
              else polygon(region['points']))
    xs, ys = zip(*points)
    candidates = grid((min(xs), min(ys), max(xs), max(ys)), values)
    radius = round(values['diameter'] * 5e5)
    ds = board.GetDesignSettings()
    clearance = max(ds.m_MinClearance,
                    ds.m_NetSettings.GetEffectiveNetClass(net.GetNetname()).GetClearance())
    boundary = round(values['boundary'] * 1e6)
    board_edge = max(round(values['edge'] * 1e6), ds.m_CopperEdgeClearance)
    layers = list(board.GetEnabledLayers().CuStack())
    zones, keepouts, foreign = [], [], []
    for zone in board.Zones():
        if zone.GetIsRuleArea():
            if (zone.GetDoNotAllowVias() and
                    any(layer in layers for layer in zone.GetLayerSet().Seq())):
                keepouts.append(zone.Outline())
        elif any(layer in layers for layer in zone.GetLayerSet().Seq()):
            if not zone.IsFilled() or zone.NeedRefill():
                raise ValueError('Copper fills are missing/stale. Refill zones in KiCad, '
                                 'then request a new preview.')
            for layer in zone.GetLayerSet().CuStack():
                poly = zone.GetFilledPolysList(layer)
                if zone.GetNetCode() == net.GetNetCode():
                    zones.append((layer, poly, uid(zone)))
                else:
                    nc = ds.m_NetSettings.GetEffectiveNetClass(zone.GetNetname())
                    foreign.append((poly, max(clearance, nc.GetClearance())))
    if len({layer for layer, _, _ in zones}) < 2:
        raise ValueError('The chosen net needs filled copper on at least two copper layers.')
    excluded = set()
    if request.get('replace'):
        for _, vias in ownership(board, [request['replace']], load_store(board.GetFileName())):
            excluded.update(uid(v) for v in vias)
    # Conservative obstacle checks: even same-net pads/tracks are avoided. Index
    # bounding boxes so full-board grids do not scan every item for every candidate.
    buckets = defaultdict(list)
    cell = 5_000_000
    items = list(board.GetTracks())
    for fp in board.GetFootprints():
        items.extend(fp.Pads())
        items.extend(g for g in fp.GraphicalItems() if g.GetLayer() in layers)
    for drawing in board.Drawings():
        if drawing.GetLayer() in layers:
            items.append(drawing)
    for item in items:
        if uid(item) in excluded:
            continue
        box = item.GetBoundingBox()
        shape_layers = [layer for layer in layers if item.IsOnLayer(layer)]
        item_clearance = clearance
        if isinstance(item, pcbnew.BOARD_CONNECTED_ITEM):
            nc = ds.m_NetSettings.GetEffectiveNetClass(item.GetNetname())
            item_clearance = max(clearance, nc.GetClearance())
        if isinstance(item, (pcbnew.PAD, pcbnew.PCB_TRACK, pcbnew.PCB_SHAPE)):
            shapes = [(item.GetEffectiveShape(layer), item_clearance) for layer in shape_layers]
            shapes = [(shape, gap) for shape, gap in shapes if shape]
        else:
            # Text and other copper graphics use a conservative box; some legacy
            # classes assert rather than providing an effective-shape implementation.
            shape = pcbnew.SHAPE_POLY_SET()
            shape.NewOutline()
            for x, y in ((box.GetX(), box.GetY()), (box.GetRight(), box.GetY()),
                         (box.GetRight(), box.GetBottom()), (box.GetX(), box.GetBottom())):
                shape.Append(x, y)
            shapes = [(shape, item_clearance)]
        if isinstance(item, (pcbnew.PAD, pcbnew.PCB_VIA)):
            hole = item.GetEffectiveHoleShape()
            if hole:
                shapes.append((hole, max(ds.m_HoleClearance, ds.m_HoleToHoleMin)))
        if not shapes:
            continue
        margin = max(item_clearance, ds.m_HoleClearance, ds.m_HoleToHoleMin) + radius
        x0, y0 = box.GetX() - margin, box.GetY() - margin
        x1, y1 = box.GetRight() + margin, box.GetBottom() + margin
        for iy in range(y0 // cell, y1 // cell + 1):
            for ix in range(x0 // cell, x1 // cell + 1):
                buckets[ix, iy].extend(shapes)
    accepted, rejected = [], []
    strict = values.get('connection', 'two') == 'all'
    for x, y in candidates:
        if time.monotonic() - started > 12:
            raise ValueError('Preview exceeded its time budget; increase spacing '
                             'or narrow the region.')
        point = pcbnew.VECTOR2I(round(x * 1e6), round(y * 1e6))
        circle = pcbnew.SHAPE_CIRCLE(point, radius)
        reason = None
        if not fits(board_poly, point, radius + board_edge):
            reason = 'board edge / cutout'
        elif region['kind'] != 'board' and not inside((x, y), points,
                                                     (radius + boundary) / 1e6):
            reason = 'region boundary'
        elif any(poly.Collide(circle) for poly in keepouts):
            reason = 'via keepout'
        elif any(poly.Collide(circle, gap) for poly, gap in foreign):
            reason = 'other-net copper'
        elif any(shape.Collide(circle, gap)
                 for shape, gap in buckets[point.x // cell, point.y // cell]):
            reason = 'pad / track / via clearance'
        else:
            contacts = {layer for layer, poly, _ in zones if fits(poly, point, radius + boundary)}
            in_selected = region['kind'] != 'zone' or any(
                key == region['uuid'] and fits(poly, point, radius + boundary)
                for _, poly, key in zones)
            if not in_selected or len(contacts) < (len(layers) if strict else 2):
                reason = 'insufficient copper contact'
        if reason:
            rejected.append([x, y, reason])
        else:
            accepted.append([x, y])
    return dict(settings=values, region=region, accepted=accepted, rejected=rejected,
                reasons=dict(Counter(p[2] for p in rejected)), clearance_mm=clearance / 1e6,
                replace=request.get('replace'), name=request.get('name') or 'Ground stitching')


def menu_item(menu, label):
    for item in menu.GetMenuItems():
        if item.GetItemLabelText() == label:
            return item
        if item.GetSubMenu():
            found = menu_item(item.GetSubMenu(), label)
            if found:
                return found
    return None


def editor_frame():
    return next((w for w in wx.GetTopLevelWindows() if isinstance(w, wx.Frame)
                 and w.GetTitle().endswith('PCB Editor')), None)


def transaction(board, job):
    global _pending
    if _pending is not None:
        raise RuntimeError('Another stitching transaction is in progress.')
    frame = editor_frame()
    item = next((found for menu, _ in frame.GetMenuBar().GetMenus()
                 if (found := menu_item(menu, COMMIT_LABEL))), None) if frame else None
    if item is None:
        raise RuntimeError('Restart PCB Editor to load the native stitching commit action.')
    _pending = dict(board=board.GetFileName(), job=job)
    try:
        event = wx.CommandEvent(wx.EVT_MENU.typeId, item.GetId())
        frame.GetEventHandler().ProcessEvent(event)
        if 'error' in _pending:
            # Native action wrapper has now captured the complete partial change.
            undo_item = next((found for menu, _ in frame.GetMenuBar().GetMenus()
                              if (found := menu_item(menu, wx.GetTranslation('Undo')))), None)
            undo = wx.CommandEvent(wx.EVT_MENU.typeId, undo_item.GetId()) if undo_item else None
            if undo is None or not frame.GetEventHandler().ProcessEvent(undo):
                raise RuntimeError('Stitching failed; use Edit > Undo before proceeding: '
                                   + _pending['error'])
            raise RuntimeError('Stitching failed and was undone: ' + _pending['error'])
        if not _pending.get('ran'):
            raise RuntimeError('KiCad did not execute the stitching action.')
        return _pending['result']
    finally:
        _pending = None


def commit_pending():
    """Called only by KiCad's ActionPlugin.Run, inside its native undo wrapper."""
    if _pending is None:
        return
    _pending['ran'] = True
    try:
        board = pcbnew.GetBoard()
        if board.GetFileName() != _pending['board']:
            raise RuntimeError('The open board changed before the transaction.')
        _pending['result'] = _pending['job'](board)
    except Exception as exc:
        _pending['error'] = str(exc)


def refill(board):
    board.BuildConnectivity()
    if list(board.Zones()) and not pcbnew.ZONE_FILLER(board).Fill(board.Zones()):
        raise RuntimeError('Zone refill did not complete.')
    board.BuildConnectivity()


def remove_members(board, chosen):
    for _, vias in chosen:
        for via in vias:
            board.RemoveNative(via)  # Native undo buffer owns removed objects.


def dispatch(board, operation, payload):
    global _preview
    if operation == 'stitch_scene':
        return scene(board)
    if operation == 'stitch_preview':
        result = plan(board, payload)
        token = secrets.token_hex(16)
        _preview = (board.GetFileName(), token, result)
        return dict(result, token=token)
    store = load_store(board.GetFileName())
    if operation == 'stitch_select':
        chosen = ownership(board, payload['ids'], store, select=True)
        for item in pcbnew.GetCurrentSelection():
            item.ClearSelected()
            if isinstance(item, pcbnew.PCB_GROUP):
                for child in item.GetItems():
                    child.ClearSelected()
        for _, vias in chosen:
            for via in vias:
                via.SetSelected()
        pcbnew.Refresh()  # Synchronizes flags with the actual native selection tool.
        return sum(len(vias) for _, vias in chosen)
    if operation == 'stitch_remove':
        chosen = ownership(board, payload['ids'], store)
        count = sum(len(vias) for _, vias in chosen)
        if not count:
            raise ValueError('No unchanged, unlocked stitching vias remain. Manually edited '
                             'or locked vias are preserved.')

        def remove(live):
            remove_members(live, chosen)
            refill(live)
            return count

        _preview = None
        return transaction(board, remove)
    if operation != 'stitch_apply':
        raise ValueError('Unsupported stitching operation.')
    if (_preview is None or _preview[:2] != (board.GetFileName(), payload.get('token'))):
        raise ValueError('Preview expired. Request a fresh preview before applying.')
    old = _preview[2]
    current = plan(board, old)
    if any(current[k] != old[k] for k in ('settings', 'region', 'accepted')):
        _preview = None
        raise ValueError('Board geometry/defaults changed. Request a fresh preview.')
    if not current['accepted']:
        raise ValueError('There are no accepted locations to place.')
    replace = ownership(board, [old['replace']], store) if old.get('replace') else []
    identity = str(uuid.uuid4())
    vias = []
    net = board.FindNet(current['settings']['net'])
    values = current['settings']
    for x, y in current['accepted']:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(round(x * 1e6), round(y * 1e6)))
        via.SetViaType(pcbnew.VIATYPE_THROUGH)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetWidth(round(values['diameter'] * 1e6))
        via.SetDrill(round(values['drill'] * 1e6))
        via.SetNetCode(net.GetNetCode())
        via.SetIsFree(True)
        vias.append(via)
    record = dict(name=current['name'], region=current['region'], settings=values,
                  vias={uid(v): [*point_mm(v.GetPosition()), v.GetWidth(pcbnew.F_Cu) / 1e6,
                                 v.GetDrillValue() / 1e6] for v in vias})
    # Journal before touching the board; retained records also allow undo/redo recovery.
    store['records'][identity] = record
    store['last'] = dict(settings=values, region=current['region'], name=current['name'])
    save_store(board.GetFileName(), store)

    def apply(live):
        remove_members(live, replace)
        for via in vias:
            live.Add(via)
        refill(live)
        # Native connectivity includes thermal spokes; an annulus-only polygon
        # containment test would incorrectly reject thermally connected vias.
        layers = list(live.GetEnabledLayers().CuStack())
        required = len(layers) if values.get('connection') == 'all' else 2
        connected = live.GetConnectivity()
        if any(sum(connected.IsConnectedOnLayer(via, layer) for layer in layers) < required
               for via in vias):
            raise RuntimeError('Copper connectivity changed after refill; placement rolled back.')
        return dict(id=identity, count=len(vias))

    _preview = None  # A mutation token is single-use, including on failure.
    return transaction(board, apply)
