"""Native asset capture and net-safe translation for selection-based Layout Clone."""
from __future__ import annotations

import math
import re
import tempfile
from collections import Counter
from pathlib import Path

MODES = ('placement', 'routing', 'both')
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_ASSETS = 10000


def selected_items(selection):
    """Expand nested groups; do not expand nets or footprint-owned children."""
    import pcbnew as k
    found = {}

    def visit(item):
        key = item.m_Uuid.AsString()
        if key in found:
            return
        found[key] = item
        if isinstance(item, k.PCB_GROUP):
            for child in item.GetItems():
                visit(child)
    for item in selection:
        visit(item)
    return list(found.values())


def category(item):
    import pcbnew as k
    if isinstance(item, k.PCB_VIA):
        return 'vias'
    if isinstance(item, k.PCB_TRACK):
        return 'arcs' if isinstance(item, k.PCB_ARC) else 'tracks'
    if isinstance(item, k.ZONE):
        return 'zones'
    classes = tuple(getattr(k, name) for name in (
        'PCB_SHAPE', 'PCB_TEXT', 'PCB_TEXTBOX', 'PCB_TABLE', 'PCB_TARGET',
        'PCB_DIM_ALIGNED', 'PCB_DIM_ORTHOGONAL', 'PCB_DIM_CENTER',
        'PCB_DIM_RADIAL', 'PCB_DIM_LEADER') if hasattr(k, name))
    if isinstance(item, classes):
        return 'graphics'
    return None


def _objects(board):
    return [*board.GetTracks(), *board.GetDrawings(), *board.Zones()]


def _duplicate(item):
    try:
        obj = item.Duplicate().Cast()
    except TypeError:  # ZONE uses the group-aware duplication overload.
        obj = item.Duplicate(False).Cast()
    obj.ClearSelected()
    return obj


def _check_asset(item):
    import pcbnew as k
    kind = category(item)
    if kind is None:
        raise ValueError('Unsupported selected layout item: ' + type(item).__name__)
    if item.GetLayer() in (k.Edge_Cuts, k.Margin):
        raise ValueError('Board outline/margin items are not circuit-layout assets; deselect them.')
    return kind


def capture(board, items):
    """Serialize selected top-level assets with KiCad, preserving native properties."""
    import pcbnew as k
    chosen = []
    for item in items:
        if category(item) is None or item.GetLayer() in (k.Edge_Cuts, k.Margin):
            continue
        if item.GetParentFootprint() is not None:
            continue  # Footprint-owned artwork belongs to the matched footprint.
        chosen.append(item)
    if len(chosen) > MAX_ASSETS:
        raise ValueError('Select at most 10000 non-footprint layout items.')
    if not chosen:
        return dict(native_board='', counts={})
    # CreateEmptyBoard() is a standalone-only factory in embedded PCB Editor:
    # it may return None, and BOARD() then wraps that invalid result. The native
    # file loader creates an independent board without either constructor path.
    with tempfile.TemporaryDirectory(prefix='traceforge-clone-capture-') as folder:
        path = Path(folder) / 'assets.kicad_pcb'
        path.write_text(
            '(kicad_pcb (version 20260206) (generator "pcbnew") '
            '(layers (0 "F.Cu" signal) (2 "B.Cu" signal)))', encoding='utf-8')
        scratch = k.LoadBoard(str(path))
        if scratch is None:
            raise RuntimeError('KiCad could not load the temporary layout capture board.')
        scratch.SetCopperLayerCount(board.GetCopperLayerCount())
        nets = {}
        for item in chosen:
            clone = _duplicate(item)
            clone.SetParent(scratch)
            if hasattr(item, 'GetNetname') and item.GetNetname():
                name = item.GetNetname()
                if name not in nets:
                    nets[name] = k.NETINFO_ITEM(scratch, name)
                    scratch.Add(nets[name])
                clone.SetNet(nets[name])
            scratch.Add(clone)
        k.SaveBoard(str(path), scratch)
        text = path.read_text(encoding='utf-8')
    if len(text.encode('utf-8')) > MAX_ASSET_BYTES:
        raise ValueError('Selected layout assets exceed 16 MB. Narrow the selection.')
    return dict(native_board=text, counts=dict(Counter(category(i) for i in chosen)),
                preview=preview_items(chosen))


def options(payload):
    mode = payload.get('mode', 'placement')
    if mode not in MODES:
        raise ValueError('Choose placement, routing, or both.')
    return mode, payload.get('include_graphics', False) is True


def net_mapping(template, target, plan):
    src = {x['ref']: x for x in template['items']}
    dst = {x['ref']: x for x in target['items']}
    mapping = {}
    reverse = {}
    for pair in plan['pairs']:
        pads = {p['number']: p['net'] for p in dst[pair['target']]['pads']}
        for pad in src[pair['source']]['pads']:
            old, new = pad['net'], pads.get(pad['number'], '')
            if not old:
                continue
            if not new or old.startswith('unconnected-') or new.startswith('unconnected-'):
                continue
            if old in mapping and mapping[old] != new:
                raise ValueError('One source net maps to multiple target nets: ' + old)
            if new in reverse and reverse[new] != old:
                raise ValueError('Distinct source nets would merge on target: ' + new)
            mapping[old], reverse[new] = new, old
    return mapping


def plan_options(template, target, plan, mode, graphics):
    """Augment the ordinary correspondence preview without editing anything."""
    issues = list(plan['issues'])
    warnings = []
    if mode == 'placement' and not plan.get('topology_matches', True):
        issues = [s for s in issues if not s.startswith('Internal pin connections differ.')]
        warnings.append('Pin connections differ: placement only retains every target net. '
                        'Routing reuse remains blocked for this mapping.')
    if mode == 'routing':
        issues = [s for s in issues if not s.startswith('Target footprints locked:')]
        dst = {x['id']: x for x in target['items']}
        bad = [p['target'] for p in plan['pairs'] if
               abs(dst[p['target_id']]['x'] - p['x']) > .00002 or
               abs(dst[p['target_id']]['y'] - p['y']) > .00002 or
               abs((dst[p['target_id']]['angle'] - p['angle'] + 180) % 360 - 180) > .00002]
        if bad:
            pass  # Reclone aligns placement automatically before replacing routing.
    counts = template.get('assets', {}).get('counts', {})
    if mode != 'placement':
        if plan['missing'] or plan['extra']:
            issues.append('Routing requires complete source and target component groups.')
        if not sum(counts.get(k, 0) for k in ('tracks', 'arcs', 'vias', 'zones')):
            issues.append('No routing recorded. Select source tracks/vias/zones with components, '
                          'then Record.')
        try:
            net_mapping(template, target, plan)
        except ValueError as exc:
            issues.append(str(exc))
    plan = dict(plan, issues=issues, can_apply=bool(plan['pairs']) and not issues,
                mode=mode, include_graphics=graphics, warnings=warnings)
    return plan


def transform_point(point, transform):
    """Rotate in KiCad board coordinates (positive angles turn toward -Y)."""
    x, y = (point[i] - transform['origin'][i] for i in (0, 1))
    angle = math.radians(transform['angle'])
    c, s = math.cos(angle), math.sin(angle)
    return [round(transform['target'][0] + c*x + s*y, 5),
            round(transform['target'][1] - s*x + c*y, 5)]


def prepare(board, template, target, plan, mode, graphics):
    """Validate and translate clones in memory before the edit transaction."""
    import pcbnew as k
    asset_data = template.get('assets', {})
    text = asset_data.get('native_board', '')
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_ASSET_BYTES:
        raise ValueError('Invalid or oversized native layout assets.')
    if not text or (mode == 'placement' and not graphics):
        return []
    with tempfile.TemporaryDirectory(prefix='traceforge-clone-parse-') as folder:
        path = Path(folder) / 'assets.kicad_pcb'
        path.write_text(text, encoding='utf-8')
        scratch = k.LoadBoard(str(path))
    if list(scratch.GetFootprints()) or list(scratch.Groups()):
        raise ValueError('Layout assets must not contain embedded components or groups.')
    objects = _objects(scratch)
    if len(objects) > MAX_ASSETS:
        raise ValueError('Too many native layout assets.')
    mapping = net_mapping(template, target, plan)
    target_nets = {n.GetNetname(): n for n in board.GetNetsByNetcode().values()}
    transform = plan['transform']
    origin = k.VECTOR2I(*(k.FromMM(n) for n in transform['origin']))
    delta = k.VECTOR2I(*(k.FromMM(transform['target'][i] - transform['origin'][i])
                          for i in (0, 1)))
    prepared = []
    existing_keys = {_native_key(i) for i in _objects(board) if category(i)}
    for item in objects:
        kind = _check_asset(item)
        is_zone = kind == 'zones'
        keepout = is_zone and item.GetIsRuleArea()
        routing = kind in ('tracks', 'arcs', 'vias') or (is_zone and not keepout)
        if not (routing and mode != 'placement' or not routing and graphics):
            continue
        clone = _duplicate(item)
        clone.SetParent(board)
        if hasattr(item, 'GetNetname') and not keepout and (routing or item.GetNetname()):
            name = str(item.GetNetname())
            if not name or name not in mapping or mapping[name] not in target_nets:
                raise ValueError('Cannot resolve selected copper net through matched pads: ' + name)
            clone.SetNet(target_nets[mapping[name]])
        if not set(clone.GetLayerSet().Seq()) <= set(board.GetEnabledLayers().Seq()):
            raise ValueError('A recorded item uses layers disabled on the target board.')
        clone.SetUuid(k.KIID())
        if isinstance(clone, k.PCB_TABLE):
            for cell in clone.GetCells():
                cell.SetUuid(k.KIID())
        clone.Rotate(origin, k.EDA_ANGLE(transform['angle'], k.DEGREES_T))
        clone.Move(delta)
        clone.SetLocked(False)
        if is_zone:
            clone.UnFill()
        key = _native_key(clone)
        if key in existing_keys:
            raise ValueError('An identical layout item already exists at the target location.')
        existing_keys.add(key)
        prepared.append(clone)
    if mode != 'placement' and not any(
            category(i) in ('tracks', 'arcs', 'vias') or
            category(i) == 'zones' and not i.GetIsRuleArea() for i in prepared):
        raise ValueError('The recorded selection contains no routable copper for this mode.')
    return prepared


def _native_key(item):
    """Ignore identities and zone fill caches when detecting an existing copy."""
    import pcbnew as k
    obj = _duplicate(item)
    obj.SetLocked(False)
    if isinstance(obj, k.ZONE):
        obj.UnFill()
    formatter = k.STRING_FORMATTER()
    writer = k.PCB_IO_KICAD_SEXPR()
    writer.SetOutputFormatter(formatter)
    writer.Format(obj)
    value = re.sub(r'\(uuid\s+[^)]+\)', '', formatter.GetString())
    return ' '.join(value.split())


def check_copper_clearance(board, additions, prospective=None, ignored=None):
    """Check copied tracks/vias against pads and existing copper before adding them.

    This uses native copper shapes, not text/footprint bounding boxes. Zone fill,
    keepout and edge/assembly constraints still need the full KiCad DRC afterward.
    """
    import pcbnew as k
    copper = [i for i in additions if isinstance(i, k.PCB_TRACK)]
    prospective = prospective or {}
    footprints = [prospective.get(fp.m_Uuid.AsString(), fp) for fp in board.GetFootprints()]
    ignored = set(ignored or ())
    obstacles = [i for i in board.GetTracks() if i.m_Uuid.AsString() not in ignored]
    obstacles += [pad for fp in footprints for pad in fp.Pads()]
    for item in copper:
        for other in [*obstacles, *copper]:
            if item == other or item.GetNetCode() == other.GetNetCode() and item.GetNetCode():
                continue
            layers = set(item.GetLayerSet().Seq()) & set(other.GetLayerSet().Seq())
            if not layers:
                continue
            for layer in layers:
                clearance = max(item.GetOwnClearance(layer), other.GetOwnClearance(layer))
                if item.GetEffectiveShape(layer).Collide(other.GetEffectiveShape(layer), clearance):
                    pos = other.GetPosition()
                    owner = other.GetParentFootprint()
                    detail = (owner.GetReference() + ' pad ' + other.GetNumber()
                              if owner else category(other))
                    raise ValueError('Copied routing violates copper clearance against '
                                     + str(detail) + ' on net ' + other.GetNetname()
                                     + f' at ({k.ToMM(pos.x):.3f}, {k.ToMM(pos.y):.3f}) mm. '
                                     'Board unchanged; move the target anchor '
                                     'to clear nearby copper.')


def preview_items(items):
    """Read-only drawing primitives, separate from the native assets used by Apply."""
    import pcbnew as k

    from .layout_clone_preview import arc_points

    def xy(point):
        return [k.ToMM(point.x), k.ToMM(point.y)]

    result = []
    for item in items:
        kind = category(item)
        layer = k.LayerName(item.GetLayer())
        if isinstance(item, k.PCB_VIA):
            result.append(dict(kind='via', points=[xy(item.GetPosition())],
                               width=k.ToMM(item.GetWidth(item.TopLayer())),
                               drill=k.ToMM(item.GetDrillValue()), layer='via'))
        elif isinstance(item, k.PCB_TRACK):
            points = (arc_points(xy(item.GetStart()), xy(item.GetMid()), xy(item.GetEnd()))
                      if isinstance(item, k.PCB_ARC) else
                      [xy(item.GetStart()), xy(item.GetEnd())])
            result.append(dict(kind='copper', points=points,
                               width=k.ToMM(item.GetWidth()), layer=layer))
        elif isinstance(item, k.ZONE):
            poly = item.Outline()
            for index in range(poly.OutlineCount()):
                outline = poly.COutline(index)
                points = [xy(outline.CPoint(i)) for i in range(outline.PointCount())]
                if points:
                    result.append(dict(kind='keepout' if item.GetIsRuleArea() else 'zone',
                                       points=points+[points[0]], width=.1, layer=layer,
                                       layers=[k.LayerName(layer_id)
                                               for layer_id in item.GetLayerSet().Seq()]))
        elif isinstance(item, k.PCB_SHAPE):
            shape = item.GetShape()
            if shape == k.SHAPE_T_SEGMENT:
                points = [xy(item.GetStart()), xy(item.GetEnd())]
            elif shape == k.SHAPE_T_RECT:
                a, b = xy(item.GetStart()), xy(item.GetEnd())
                points = [a, [b[0], a[1]], b, [a[0], b[1]], a]
            elif shape == k.SHAPE_T_CIRCLE:
                c = xy(item.GetCenter())
                r = k.ToMM(item.GetRadius())
                points = [[c[0]+r*math.cos(i*math.pi/24), c[1]+r*math.sin(i*math.pi/24)]
                          for i in range(49)]
            elif shape == k.SHAPE_T_ARC:
                points = arc_points(xy(item.GetStart()), xy(item.GetArcMid()), xy(item.GetEnd()))
            else:
                box = item.GetBoundingBox()
                a, b = xy(box.GetOrigin()), xy(box.GetEnd())
                points = [a, [b[0], a[1]], b, [a[0], b[1]], a]
            result.append(dict(kind='graphics', points=points,
                               width=max(.05, k.ToMM(item.GetWidth())), layer=layer))
        elif kind == 'graphics':
            text = item.GetText() if hasattr(item, 'GetText') else type(item).__name__
            result.append(dict(kind='text', points=[xy(item.GetPosition())],
                               text=str(text), width=.1, layer=layer))
    return result


def preview_from_native(text):
    """Read legacy templates that predate cached drawing primitives."""
    import pcbnew as k
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_ASSET_BYTES:
        raise ValueError('Invalid native layout preview data.')
    if not text:
        return []
    with tempfile.TemporaryDirectory(prefix='traceforge-clone-preview-') as folder:
        path = Path(folder) / 'assets.kicad_pcb'
        path.write_text(text, encoding='utf-8')
        scratch = k.LoadBoard(str(path))
        if scratch is None:
            raise ValueError('Cannot read recorded layout for preview.')
        return preview_items(_objects(scratch))
