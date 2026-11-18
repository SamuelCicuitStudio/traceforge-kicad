"""Selection-based layout reuse for TraceForge; no schematic hierarchy required.

The pure planner matches numbered pad geometry, values and internal circuit roles.
The native adapter captures the live selection and applies one undoable transaction.
The panel keeps the template for repeated target groups or JSON save/load.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import layout_clone_assets as assets
from . import layout_clone_hierarchy as hierarchy

FORMAT_VERSION = 1
INVALID = -1_000_000
MAX_SELECTION = 500
_NET_CHANNEL = re.compile(r'(?i)(CAN|READER|SIM|UART|CHANNEL|CH|PORT|LANE)[_-]?0*\d+')
_NET_SIGNAL = re.compile(r'(?i)(?<![A-Z])(TX|RX|CLK|RST|RESET|CS)[_-]?0*\d+(?=\b|_|/)')


def normalize_net(name: str) -> str:
    """Normalize repeating circuit indices without requiring hierarchical sheets.

    /CAN1_TERM_H == /CAN3_TERM_H, /READER_05/SEC_TXD == /READER_14/SEC_TXD.
    Net labels are a matching hint, not the only way components are matched.
    """
    name = str(name or '').replace('{slash}', '/').strip().upper()
    name = _NET_CHANNEL.sub(lambda m: m.group(1).upper() + '#', name)
    name = _NET_SIGNAL.sub(lambda m: m.group(1).upper() + '#', name)
    return name


def norm_angle(value: float) -> float:
    x = float(value) % 360.0
    return round(0.0 if abs(x - 360) < 1e-6 else x, 5)


def rmm(x: float) -> float:
    return round(float(x), 5)


def geometry_key(item: dict) -> tuple:
    """Pad-numbered physical pinout; identical names alone are insufficient."""
    pads = []
    for p in item['pads']:
        pads.append((str(p['number']), int(p['shape']), int(p['type']),
                     tuple(round(float(n), 3) for n in p['size']),
                     tuple(round(float(n), 3) for n in p['local']),
                     round(norm_angle(p['local_angle']), 3),
                     tuple(p.get('drill', ())), p.get('layers', '')))
    name = str(item['footprint']).split(':')[-1].upper()
    return (name, str(item['layer']), tuple(sorted(pads)))


def value_key(item: dict) -> str:
    value = str(item.get('value', '')).upper()
    # Functional connector labels identify channel instances, not different parts.
    # Keep the IDC/role suffix; do not normalize arbitrary connector MPNs.
    if str(item.get('ref', '')).startswith('J') and re.match(
            r'^(?:SIM|READER|UART|CHANNEL|CH|PORT|LANE)[ _-]?\d+\s*/\s*.+', value):
        value = normalize_net(value)
    return re.sub(r'\s+', '', value)


def pad_key(pad: dict) -> tuple:
    return (str(pad['number']), tuple(round(float(v), 5) for v in pad['local']))


def index_nets(items: list[dict]):
    by_net = defaultdict(list)
    for it in items:
        for pad in it['pads']:
            net = pad.get('net', '')
            if net:
                by_net[net].append((it, pad))
    # Propagate roles through series parts: two identical capacitors can be
    # distinguished by which numbered IC pin their otherwise identical RC branch serves.
    def digest(value):
        return hashlib.sha256(repr(value).encode('utf-8')).hexdigest()

    geometry = {it['id']: geometry_key(it) for it in items}
    values = {it['id']: value_key(it) for it in items}
    colors = {it['id']: digest((geometry[it['id']], values[it['id']])) for it in items}
    role_colors = {}
    for _ in range(3):
        role_colors = {}
        for it in items:
            roles = {}
            for pad in it['pads']:
                roles[pad_key(pad)] = digest(sorted(
                    (str(other_pad['number']), colors[other['id']])
                    for other, other_pad in by_net.get(pad.get('net'), [])
                    if other['id'] != it['id']))
            role_colors[it['id']] = roles
        colors = {it['id']: digest((colors[it['id']], sorted(role_colors[it['id']].items())))
                  for it in items}
    # Per-component, per-pad role from other components attached to the same net.
    result = {}
    for it in items:
        pdata = {}
        for pad in it['pads']:
            net = pad.get('net', '')
            neighbors = []
            for other, other_pad in by_net.get(net, []):
                if other['id'] != it['id']:
                    neighbors.append((geometry[other['id']][0], values[other['id']],
                                      str(other_pad['number'])))
            pdata[pad_key(pad)] = (
                len(by_net.get(net, ())) if net else 0,
                Counter(neighbors),
                role_colors[it['id']][pad_key(pad)],
            )
        result[it['id']] = pdata
    return result


def compatibility(source: dict, target: dict, src_network=None, dst_network=None) -> int:
    """Compatibility score. INVALID means the physical pad arrangement differs."""
    if geometry_key(source) != geometry_key(target):
        return INVALID
    score = 120
    score += 28 if value_key(source) == value_key(target) else -30
    sp = sorted(source['pads'], key=lambda p: (str(p['number']), p['local']))
    tp = sorted(target['pads'], key=lambda p: (str(p['number']), p['local']))
    sn = (src_network or {}).get(source['id'], {})
    tn = (dst_network or {}).get(target['id'], {})
    for p, q in zip(sp, tp):
        an, bn = normalize_net(p.get('net')), normalize_net(q.get('net'))
        if an and bn and an == bn:
            score += 14 if an not in ('GND', '3V3', '+3V3', '+5V', '5V') else 5
            if str(p.get('net')) == str(q.get('net')):
                score += 2
        elif not an and not bn:
            score += 3
        else:
            score -= 3  # hint only; different naming conventions are allowed
        pn = pad_key(p)
        degree_a, adjacent_a, role_a = sn.get(pn, (0, Counter(), None))
        degree_b, adjacent_b, role_b = tn.get(pn, (0, Counter(), None))
        score += 3 if degree_a == degree_b else -3
        score += 8 * sum((adjacent_a & adjacent_b).values())
        score -= 2 * sum((adjacent_a - adjacent_b).values())
        if role_a and role_b:
            score += 40 if role_a == role_b else -2
    return score


def best_assignment(scores: list[list[int]]) -> list[int | None]:
    """Maximum weight bipartite assignment with dummy columns (no scipy)."""
    n = len(scores)
    if not n:
        return []
    m_real = len(scores[0])
    m = m_real + n
    # Hungarian min-cost solver; allow a source to remain unmatched at weight zero.
    costs = [[-v for v in row] + [0] * n for row in scores]
    u, v, p, way = [0] * (n + 1), [0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        minv = [float('inf')] * (m + 1)
        used = [False] * (m + 1)
        j0 = 0
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = float('inf'), 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = costs[i0-1][j-1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [None] * n
    for j in range(1, m + 1):
        if p[j] and j <= m_real and scores[p[j]-1][j-1] > 0:
            result[p[j]-1] = j - 1
    return result


def _validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('format') != FORMAT_VERSION:
        raise ValueError('Not a TraceForge Layout Clone template/snapshot.')
    items = snapshot.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_SELECTION:
        raise ValueError('A snapshot must contain 1 to 500 footprint records.')
    ids, refs = set(), set()
    for it in items:
        if not isinstance(it, dict) or not all(k in it for k in
                ('id', 'ref', 'x', 'y', 'angle', 'pads', 'footprint', 'layer')):
            raise ValueError('Invalid component record.')
        if it['id'] in ids or it['ref'] in refs:
            raise ValueError('Duplicate component identity or reference in selection.')
        ids.add(it['id'])
        refs.add(it['ref'])
        for key in ('x', 'y', 'angle'):
            if not math.isfinite(float(it[key])):
                raise ValueError('Invalid coordinate or rotation.')
        if not isinstance(it['pads'], list) or len(it['pads']) > 2000:
            raise ValueError('Invalid or oversized pad list.')
        for pad in it['pads']:
            try:
                numbers = [*pad['size'], *pad['local'], pad['local_angle']]
                valid = (len(pad['size']) == len(pad['local']) == 2 and
                         all(math.isfinite(float(n)) for n in numbers) and
                         all(float(n) > 0 for n in pad['size']))
                int(pad['shape'])
                int(pad['type'])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError('Invalid pad geometry in template.') from exc
            if not valid:
                raise ValueError('Invalid pad geometry in template.')
        geometry_key(it)  # validate geometry fields
    return items


def connection_partition(items, refs):
    """Numbered-pad connectivity within matched components, ignoring net names."""
    nets = defaultdict(set)
    for item in items:
        if item['ref'] not in refs:
            continue
        for pad in item['pads']:
            if pad.get('net'):
                nets[pad['net']].add((refs[item['ref']], pad_key(pad)))
    return {frozenset(pins) for pins in nets.values() if len(pins) > 1}


def make_plan(template: dict, target: dict, overrides: dict | None = None,
              anchor_source: str | None = None, *,
              accept_value_changes: bool = False,
              allow_partial: bool = False) -> dict:
    """Pure planner. Refuses ambiguous/missing/unsafe matches until resolved."""
    src, dst = _validate_snapshot(template), _validate_snapshot(target)
    if {x['id'] for x in src} & {x['id'] for x in dst}:
        raise ValueError('Source and target selections overlap. Select a DIFFERENT group.')
    explicit_overrides = dict(overrides or {})
    sheet_matches = hierarchy.correspondences(template, target)
    if template.get('scope') == 'hierarchy' and any(
            ref in sheet_matches and sheet_matches[ref] != dstref
            for ref, dstref in explicit_overrides.items()):
        raise ValueError('Manual assignment conflicts with repeated-sheet symbol identity.')
    overrides = {**sheet_matches, **explicit_overrides}
    src_by_ref = {it['ref']: it for it in src}
    dst_by_ref = {it['ref']: it for it in dst}
    if not set(overrides) <= set(src_by_ref):
        raise ValueError('Override refers to an unknown recorded component.')
    if (len(set(overrides.values())) != len(overrides) or
            not set(overrides.values()) <= set(dst_by_ref)):
        raise ValueError(
            'Overrides must specify distinct target components from this selection.')
    source_network, target_network = index_nets(src), index_nets(dst)
    for sref, tref in overrides.items():
        if compatibility(src_by_ref[sref], dst_by_ref[tref]) == INVALID:
            raise ValueError(f'Incompatible pad geometry: {sref} cannot map to {tref}.')
    free_src = [s for s in src if s['ref'] not in overrides]
    occupied = set(overrides.values())
    free_dst = [d for d in dst if d['ref'] not in occupied]
    scores = [[compatibility(s, d, source_network, target_network) for d in free_dst]
              for s in free_src]
    assignment = best_assignment(scores)
    mapped = {ref: dst_by_ref[tref] for ref, tref in overrides.items()}
    assigned_score = {}
    for s in free_src:
        assigned_score[s['ref']] = None
    for i, col in enumerate(assignment):
        if col is not None:
            s, d = free_src[i], free_dst[col]
            mapped[s['ref']] = d
            assigned_score[s['ref']] = scores[i][col]
    pairs = []
    ambiguous = []
    for s in src:
        d = mapped.get(s['ref'])
        if d is None:
            continue
        score = assigned_score.get(s['ref'])
        if score is None:
            score = compatibility(s, d, source_network, target_network)
        alternatives = []
        if s['ref'] not in overrides:
            # Conservative ambiguity check: other plausible equivalent footprints
            # within a small score difference (even if the assignment picked one).
            for cand in free_dst:
                if cand['id'] == d['id']:
                    continue
                candidate = compatibility(s, cand, source_network, target_network)
                if candidate != INVALID and candidate >= score - 6:
                    alternatives.append(cand['ref'])
        # Duplicates on exactly the same numbered-pad nets are electrically
        # interchangeable. Their assignment never requires a manual row selection.
        def interchangeable(candidate, d=d):
            def pins(item):
                return sorted((pad['number'], pad['net']) for pad in item['pads'])
            return (geometry_key(d) == geometry_key(candidate) and
                    value_key(d) == value_key(candidate) and pins(d) == pins(candidate))
        alternatives = [ref for ref in alternatives if not interchangeable(dst_by_ref[ref])]
        if alternatives:
            ambiguous.append(dict(source=s['ref'], target=d['ref'], alternatives=alternatives))
        pairs.append(dict(source=s['ref'], target=d['ref'], source_id=s['id'],
                          target_id=d['id'], score=score,
                          status=('Hierarchy' if s['ref'] in sheet_matches and
                                  s['ref'] not in explicit_overrides else
                                  'Manual' if s['ref'] in overrides else
                                  'Ambiguous' if alternatives else
                                  'Value differs' if value_key(s) != value_key(d) else 'Matched')))
    used = {p['target'] for p in pairs}
    missing = [s['ref'] for s in src if s['ref'] not in mapped]
    extra = [d['ref'] for d in dst if d['ref'] not in used]
    locked = [p['target'] for p in pairs if dst_by_ref[p['target']].get('locked')]
    value_differences = [p['source'] for p in pairs if
                         value_key(src_by_ref[p['source']]) != value_key(dst_by_ref[p['target']])]
    by_src = {p['source']: p for p in pairs}
    if anchor_source is not None and anchor_source not in by_src:
        raise ValueError('Chosen anchor is not among the matched components.')
    if anchor_source is None and pairs:
        anchor_source = max(
            pairs,
            key=lambda p: (len(src_by_ref[p['source']]['pads']),
                           p['score'], p['source']),
        )['source']
    if anchor_source:
        s_anchor = src_by_ref[anchor_source]
        d_anchor = dst_by_ref[by_src[anchor_source]['target']]
        dx, dy = d_anchor['x'] - s_anchor['x'], d_anchor['y'] - s_anchor['y']
        rotation = norm_angle(d_anchor['angle'] - s_anchor['angle'])
        transform = dict(origin=[s_anchor['x'], s_anchor['y']],
                         target=[d_anchor['x'], d_anchor['y']], angle=rotation)
        for p in pairs:
            s = src_by_ref[p['source']]
            p['x'], p['y'] = assets.transform_point([s['x'], s['y']], transform)
            p['angle'] = norm_angle(s['angle'] + rotation)
    else:
        dx, dy = None, None
        transform = dict(origin=[0, 0], target=[0, 0], angle=0)
    issues = []
    if missing and not allow_partial:
        issues.append('Missing target equivalents: ' + ', '.join(missing))
    if extra and not allow_partial:
        issues.append('Extra selected target components: ' + ', '.join(extra))
    if ambiguous:
        issues.append('Ambiguous matches: ' + ', '.join(p['source'] for p in ambiguous) +
                      '. These parts have different electrical connections; automatic matching '
                      'cannot distinguish them. Check the selected groups '
                      'or use optional match editing.')
    if locked:
        issues.append('Target footprints locked: ' + ', '.join(locked))
    if value_differences and not accept_value_changes:
        issues.append('Different values need review: ' + ', '.join(value_differences))
    source_refs = {p['source']: p['source'] for p in pairs}
    target_refs = {p['target']: p['source'] for p in pairs}
    topology_matches = (connection_partition(src, source_refs) ==
                        connection_partition(dst, target_refs))
    if not topology_matches:
        issues.append('Internal pin connections differ. Correct the assignments or selection.')
    return dict(pairs=pairs, anchor=anchor_source, delta=[dx, dy], transform=transform,
                missing=missing, extra=extra, ambiguous=ambiguous,
                locked=locked, value_differences=value_differences,
                topology_matches=topology_matches,
                issues=issues, can_apply=bool(pairs) and not issues)


def _pmm(p):
    return (rmm(p.x / 1e6), rmm(p.y / 1e6))


def _uuid(obj) -> str:
    return obj.m_Uuid.AsString()


def _selected_footprints(board):
    import pcbnew
    found = {}
    for item in assets.selected_items(pcbnew.GetCurrentSelection()):
        if isinstance(item, pcbnew.FOOTPRINT):
            found[_uuid(item)] = item
        elif hasattr(item, 'GetParentFootprint'):
            parent = item.GetParentFootprint()
            if parent is not None:
                found[_uuid(parent)] = parent
    # CurrentSelection covers real picked items; don't expand via net membership.
    if not found:
        for fp in board.GetFootprints():
            if fp.IsSelected():
                found[_uuid(fp)] = fp
    if not 1 <= len(found) <= MAX_SELECTION:
        raise ValueError('Select between 1 and 500 footprints in PCB Editor first.')
    return sorted(found.values(), key=lambda x: x.GetReference())


def _footprint_name(fp):
    try:
        result = fp.GetFPIDAsString()
        if result:
            return str(result)
    except (AttributeError, TypeError):
        pass
    try:
        obj = fp.GetFPID()
        return str(obj.GetLibNickname()) + ':' + str(obj.GetLibItemName())
    except (AttributeError, TypeError):
        return str(fp.GetValue())


def _pad_local(pad, fp):
    try:
        return _pmm(pad.GetFPRelativePosition())
    except (AttributeError, TypeError):
        # KiCad's local coordinates rotate with footprint angle. Inverse of the
        # common KiCad footprint-coordinate transform for a fallback only.
        px, py = _pmm(pad.GetPosition())
        ox, oy = _pmm(fp.GetPosition())
        theta = math.radians(float(fp.GetOrientationDegrees()))
        dx, dy = px - ox, py - oy
        return (rmm(dx * math.cos(theta) - dy * math.sin(theta)),
                rmm(dx * math.sin(theta) + dy * math.cos(theta)))


def _snapshot_fp(board, fp):
    pads = []
    for pad in fp.Pads():
        size = pad.GetSize()
        drill = pad.GetDrillSize()
        pads.append(dict(number=str(pad.GetNumber()),
                         shape=int(pad.GetShape()), type=int(pad.GetAttribute()),
                         size=[rmm(size.x / 1e6), rmm(size.y / 1e6)],
                         drill=[rmm(drill.x / 1e6), rmm(drill.y / 1e6)],
                         roundrect_ratio=float(pad.GetRoundRectRadiusRatio()),
                         layers=pad.GetLayerSet().FmtHex(),
                         local=list(_pad_local(pad, fp)),
                         local_angle=norm_angle(pad.GetFPRelativeOrientation().AsDegrees()),
                         net=str(pad.GetNetname()).replace('{slash}', '/'),
                         pad_id=_uuid(pad)))
    x, y = _pmm(fp.GetPosition())
    return dict(id=_uuid(fp), ref=str(fp.GetReference()),
                footprint=_footprint_name(fp), value=str(fp.GetValue()),
                layer=str(board.GetLayerName(fp.GetLayer())),
                x=x, y=y, angle=norm_angle(fp.GetOrientationDegrees()),
                locked=bool(fp.IsLocked()), pads=pads,
                schematic_path=hierarchy.path_parts(fp.GetPath().AsString()),
                sheet_file=str(fp.GetSheetfile()),
                text_layout=[dict(kind=kind, position=list(_pmm(field.GetPosition())),
                                  angle=field.GetTextAngleDegrees(), layer=field.GetLayer(),
                                  size=list(_pmm(field.GetTextSize())),
                                  thickness=field.GetTextThickness() / 1e6,
                                  hjustify=int(field.GetHorizJustify()),
                                  vjustify=int(field.GetVertJustify()),
                                  mirrored=field.IsMirrored())
                             for kind, field in [('reference', fp.Reference()),
                                                 ('value', fp.Value())]])


def _snapshot(board, fps):
    return dict(format=FORMAT_VERSION, board=str(board.GetFileName()),
                items=[_snapshot_fp(board, fp) for fp in fps])


def _scope_snapshot(board, payload):
    fps = _selected_footprints(board)
    scope = payload.get('scope', 'selection')
    if scope not in ('selection', 'hierarchy'):
        raise ValueError('Choose selected items or a repeated sheet instance.')
    root = ()
    levels = int(payload.get('parent_levels', 0))
    if not 0 <= levels <= 8:
        raise ValueError('Parent sheet levels must be between 0 and 8.')
    if scope == 'hierarchy':
        root = hierarchy.common_sheet(fp.GetPath().AsString() for fp in fps)
        if levels:
            root = root[:-levels]
        if not root:
            raise ValueError('Select footprints in one child sheet instance. '
                             'Expansion to the project root is not allowed.')
        fps = sorted((fp for fp in board.GetFootprints()
                      if hierarchy.path_parts(fp.GetPath().AsString())[:len(root)] == root),
                     key=lambda fp: fp.GetReference())
        if len(fps) > MAX_SELECTION:
            raise ValueError('Sheet instance exceeds the 500-footprint clone limit.')
    snap = _snapshot(board, fps)
    snap.update(scope=scope, parent_levels=levels, hierarchy_root=root)
    return snap, fps


def _internal_sheet_assets(board, fps):
    """Auto-capture routes only on nets whose every footprint pad is in the sheet.

    Shared power and boundary nets need explicit selection; never pull in another
    circuit's routing merely because it has the same net name.
    """
    selected = {_uuid(fp) for fp in fps}
    inside, outside = set(), set()
    for fp in board.GetFootprints():
        nets = {pad.GetNetCode() for pad in fp.Pads() if pad.GetNetCode()}
        (inside if _uuid(fp) in selected else outside).update(nets)
    local_nets = inside - outside
    return [item for item in board.GetTracks() if item.GetNetCode() in local_nets]


def _connected_target_copper(board, selected):
    """Conservative local routing guard: track/via bboxes touching target pad bboxes."""
    pad_regions = []
    for fp in selected:
        for pad in fp.Pads():
            net = int(pad.GetNetCode())
            if net <= 0:
                continue
            box = pad.GetBoundingBox()
            pad_regions.append((str(fp.GetReference()), net,
                                box.GetLeft()-50000, box.GetRight()+50000,
                                box.GetTop()-50000, box.GetBottom()+50000))
    if not pad_regions:
        return {}
    by_net = defaultdict(list)
    for ref, net, *bbox in pad_regions:
        by_net[net].append((ref, *bbox))
    hits = Counter()
    for track in board.GetTracks():
        net = int(track.GetNetCode())
        if net not in by_net:
            continue
        box = track.GetBoundingBox()
        left, right, top, bottom = box.GetLeft(), box.GetRight(), box.GetTop(), box.GetBottom()
        touched = set()
        for ref, a, b, c, d in by_net[net]:
            if left <= b and right >= a and top <= d and bottom >= c:
                touched.add(ref)
        for ref in touched:
            hits[ref] += 1
    return dict(hits)


def _pad_identity(record):
    return sorted((p['number'], p['net'], p['pad_id']) for p in record['pads'])


def _is_same_live_record(old, new) -> bool:
    return (old['id'] == new['id'] and old['ref'] == new['ref'] and
            abs(old['x'] - new['x']) < 0.00002 and
            abs(old['y'] - new['y']) < 0.00002 and
            abs((old['angle'] - new['angle'] + 180) % 360 - 180) < 0.00002 and
            geometry_key(old) == geometry_key(new) and
            value_key(old) == value_key(new) and
            bool(old.get('locked')) == bool(new.get('locked')) and
            _pad_identity(old) == _pad_identity(new) and
            hierarchy.path_parts(old.get('schematic_path')) ==
            hierarchy.path_parts(new.get('schematic_path')))


def _apply_to_board(board, payload):
    import pcbnew

    from signal_path_analyzer.stitching_native import refill, transaction
    template = payload.get('template')
    expected = payload.get('expected_target')
    overrides = payload.get('overrides') or {}
    anchor = payload.get('anchor') or None
    _validate_snapshot(template)
    previous = _validate_snapshot(expected)
    if os.path.normcase(os.path.abspath(str(expected.get('board', '')))) != \
            os.path.normcase(os.path.abspath(str(board.GetFileName()))):
        raise ValueError('The active board changed. Analyze the target selection again.')
    ids = [p['id'] for p in previous]
    by_id = {_uuid(fp): fp for fp in board.GetFootprints()}
    if not all(pid in by_id for pid in ids):
        raise ValueError('Selected target components changed. Analyze selection again.')
    fps = [by_id[pid] for pid in ids]
    if expected.get('scope') == 'hierarchy':
        root = hierarchy.path_parts(expected.get('hierarchy_root'))
        live_ids = {_uuid(fp) for fp in board.GetFootprints()
                    if hierarchy.path_parts(fp.GetPath().AsString())[:len(root)] == root}
        if not root or live_ids != set(ids):
            raise ValueError('Target sheet membership changed. Preview again.')
    current = _snapshot(board, fps)
    current.update(scope=expected.get('scope', 'selection'),
                   hierarchy_root=expected.get('hierarchy_root', ()))
    mode, graphics = assets.options(payload)
    if any(not _is_same_live_record(a, b) or
           graphics and a.get('text_layout') != b.get('text_layout')
           for a, b in zip(previous, current['items'])):
        raise ValueError('Target footprint placement, pads, or nets changed. Analyze again.')
    plan = make_plan(template, current, overrides=overrides, anchor_source=anchor,
                     accept_value_changes=payload.get('accept_value_changes') is True,
                     allow_partial=payload.get('allow_partial') is True)
    plan = assets.plan_options(template, current, plan, mode, graphics)
    if not plan['can_apply']:
        raise ValueError('Unsafe mapping: ' + '; '.join(plan['issues']))
    changed_fps = [by_id[p['target_id']] for p in plan['pairs']]
    touching = sum(_connected_target_copper(board, changed_fps).values())
    if touching:
        raise ValueError(f'{touching} existing copper segments/vias touch target pads. '
                         'Unroute this target group before moving it.')
    additions = assets.prepare(board, template, current, plan, mode, graphics)
    changes = plan['pairs'] if mode != 'routing' else []
    # Validate prospective pad positions on duplicates, never on the live board.
    prospective = {}
    for entry in changes:
        fp = by_id[entry['target_id']].Duplicate(False).Cast()
        fp.SetOrientationDegrees(entry['angle'])
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(entry['x']),
                                     pcbnew.FromMM(entry['y'])))
        prospective[entry['target_id']] = fp
    assets.check_copper_clearance(board, additions, prospective)
    # All preflight validation ends above; edit only matched footprints, atomically.
    def job(live):
        refreshed = {_uuid(fp): fp for fp in live.GetFootprints()}
        for entry in changes:
            fp = refreshed[entry['target_id']]
            if fp.IsLocked():
                raise ValueError('Target footprint became locked: ' + entry['target'])
            # Native FOOTPRINT setters transform all pads and text as a unit.
            # Never alter pad-local (at ...) fields directly.
            fp.SetOrientationDegrees(entry['angle'])
            fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(entry['x']),
                                           pcbnew.FromMM(entry['y'])))
        if graphics:
            source_records = {r['ref']: r for r in template['items']}
            for pair in plan['pairs']:
                fp = refreshed[pair['target_id']]
                for style in source_records[pair['source']].get('text_layout', []):
                    field = fp.Reference() if style['kind'] == 'reference' else fp.Value()
                    if field.IsLocked():
                        raise ValueError('Target text is locked: ' + pair['target'])
                    if style['layer'] not in live.GetEnabledLayers().Seq():
                        raise ValueError('Source text uses a disabled target layer.')
                    x, y = assets.transform_point(style['position'], plan['transform'])
                    field.SetPosition(pcbnew.VECTOR2I(
                        pcbnew.FromMM(x), pcbnew.FromMM(y)))
                    field.SetTextAngleDegrees(style['angle'] + plan['transform']['angle'])
                    field.SetHorizJustify(style.get('hjustify', 0))
                    field.SetVertJustify(style.get('vjustify', 0))
                    field.SetMirrored(style.get('mirrored', False))
                    field.SetLayer(style['layer'])
                    field.SetTextSize(pcbnew.VECTOR2I(
                        *(pcbnew.FromMM(v) for v in style['size'])))
                    field.SetAutoThickness(False)
                    field.SetTextThickness(pcbnew.FromMM(style['thickness']))
        for item in additions:
            live.Add(item)
        for a in current['items']:
            fp = refreshed[a['id']]
            now = _snapshot_fp(live, fp)
            if geometry_key(a) != geometry_key(now):
                raise RuntimeError(f'Pad geometry/orientation changed: {a["ref"]}. Undoing.')
            if _pad_identity(a) != _pad_identity(now):
                raise RuntimeError(f'Pad identity or net changed: {a["ref"]}. Undoing.')
        refill(live)
        pcbnew.Refresh()
        return dict(moved=len(changes), cloned_assets=len(additions),
                    asset_counts=dict(Counter(assets.category(a) for a in additions)),
                    anchor=plan['anchor'],
                    distance=[rmm(n) for n in plan['delta']])
    return transaction(board, job)


def dispatch(board, operation: str, payload: dict):
    """TraceForge native_bridge/server.py dispatcher hook; editor wx main thread."""
    if operation == 'layout_clone_capture':
        snap, fps = _scope_snapshot(board, payload)
        import pcbnew
        mode, graphics = assets.options(payload)
        chosen = assets.selected_items(pcbnew.GetCurrentSelection())
        chosen = [i for i in chosen if
                  assets.category(i) in ('tracks', 'arcs', 'vias', 'zones') and
                  mode != 'placement' or graphics and assets.category(i) in ('graphics', 'zones')]
        if snap['scope'] == 'hierarchy' and mode != 'placement':
            chosen = list({_uuid(item): item for item in
                           chosen + _internal_sheet_assets(board, fps)}.values())
        snap['assets'] = assets.capture(board, chosen)
        return snap
    if operation == 'layout_clone_target':
        snap, fps = _scope_snapshot(board, payload)
        return dict(snapshot=snap,
                    copper_by_ref=_connected_target_copper(board, fps))
    if operation == 'layout_clone_apply':
        return _apply_to_board(board, payload)
    raise ValueError('Unknown layout-clone native operation: ' + operation)


def create_tab(parent, native_call):
    """Build one TraceForge wx.Notebook tab. Runs in TraceForge's panel process."""
    import wx

    class LayoutCloneTab(wx.Panel):
        def __init__(self):
            super().__init__(parent)
            self.call = native_call
            self.template = None
            self.target = None
            self.copper = 0
            self.copper_by_ref = {}
            self.plan = None
            self.overrides = {}
            self.anchor = None
            root = wx.BoxSizer(wx.VERTICAL)
            help_text = wx.StaticText(self, label=(
                'Select source footprints in KiCad -> Record. Select another group -> '
                'Apply. Matching is automatic; Preview is optional. '
                'Select routing/graphics with the source components to record them. '
                'Repeated sheet scope expands one selected footprint to its sheet and subsheets.'))
            help_text.Wrap(850)
            root.Add(help_text, 0, wx.ALL | wx.EXPAND, 10)
            row = wx.BoxSizer(wx.HORIZONTAL)
            self.record_btn = wx.Button(self, label='1  Record selected layout')
            self.scan_btn = wx.Button(self, label='Preview selected target')
            self.apply_btn = wx.Button(self, label='2  Apply to selected group (Undoable)')
            self.apply_btn.Disable()
            for button, handler in ((self.record_btn, self.on_record),
                                    (self.scan_btn, self.on_scan),
                                    (self.apply_btn, self.on_apply)):
                button.Bind(wx.EVT_BUTTON, handler)
                row.Add(button, 0, wx.RIGHT, 8)
            root.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            options = wx.BoxSizer(wx.HORIZONTAL)
            options.Add(wx.StaticText(self, label='Anchor (recorded footprint):'), 0,
                        wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 7)
            self.anchor_choice = wx.Choice(self, choices=[])
            self.anchor_choice.Bind(wx.EVT_CHOICE, self.on_anchor)
            options.Add(self.anchor_choice, 0, wx.RIGHT, 20)
            self.override_btn = wx.Button(self, label='Assign selected row…')
            self.override_btn.Bind(wx.EVT_BUTTON, self.on_override)
            options.Add(self.override_btn, 0, wx.RIGHT, 7)
            self.reset_btn = wx.Button(self, label='Clear manual assignments')
            self.reset_btn.Bind(wx.EVT_BUTTON, self.on_reset)
            options.Add(self.reset_btn)
            root.Add(options, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            mode_row = wx.BoxSizer(wx.HORIZONTAL)
            mode_row.Add(wx.StaticText(self, label='Clone:'), 0,
                         wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            self.clone_mode = wx.Choice(self, choices=[
                'Placement only', 'Routing only', 'Placement + routing'])
            self.clone_mode.SetSelection(0)
            self.clone_mode.Bind(wx.EVT_CHOICE, self.on_option)
            mode_row.Add(self.clone_mode, 0, wx.RIGHT, 18)
            self.include_graphics = wx.CheckBox(
                self, label='Also copy selected graphics / keepouts')
            self.include_graphics.Bind(wx.EVT_CHECKBOX, self.on_option)
            mode_row.Add(self.include_graphics, 0, wx.ALIGN_CENTER_VERTICAL)
            root.Add(mode_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            scope_row = wx.BoxSizer(wx.HORIZONTAL)
            scope_row.Add(wx.StaticText(self, label='Scope:'), 0,
                          wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            self.scope = wx.Choice(self, choices=['Selected items', 'Repeated sheet instance'])
            self.scope.SetSelection(0)
            scope_row.Add(self.scope, 0, wx.RIGHT, 14)
            scope_row.Add(wx.StaticText(self, label='Parent sheet levels:'), 0,
                          wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            self.parent_levels = wx.SpinCtrl(self, min=0, max=8, initial=0, size=(70, -1))
            scope_row.Add(self.parent_levels)
            root.Add(scope_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            flags = wx.BoxSizer(wx.HORIZONTAL)
            self.allow_partial = wx.CheckBox(
                self, label='Allow partial matches (unmatched parts untouched)')
            self.allow_values = wx.CheckBox(self, label='Accept different component values')
            for item in (self.allow_partial, self.allow_values):
                flags.Add(item, 0, wx.RIGHT, 22)
                item.Bind(wx.EVT_CHECKBOX, self.on_option)
            root.Add(flags, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            for i, (label, width) in enumerate((('Recorded', 140), ('Target', 140),
                                                ('Match', 160), ('Score', 80),
                                                ('New position X/Y mm', 210),
                                                ('Rotation', 100))):
                self.table.InsertColumn(i, label, width=width)
            from .layout_clone_preview import create_preview
            self.preview = create_preview(self)
            preview_box = wx.BoxSizer(wx.VERTICAL)
            controls = wx.BoxSizer(wx.HORIZONTAL)
            controls.Add(wx.StaticText(self, label='Result preview'), 0,
                         wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
            self.preview_layer = wx.Choice(self, choices=['All layers', 'F.Cu', 'B.Cu'])
            self.preview_layer.SetSelection(0)
            self.preview_layer.Bind(wx.EVT_CHOICE, self.on_preview_option)
            controls.Add(self.preview_layer, 0, wx.RIGHT, 8)
            self.preview_before = wx.CheckBox(self, label='Show before')
            self.preview_before.SetValue(True)
            self.preview_before.Bind(wx.EVT_CHECKBOX, self.on_preview_option)
            controls.Add(self.preview_before, 0, wx.RIGHT, 8)
            fit = wx.Button(self, label='Fit', style=wx.BU_EXACTFIT)
            fit.Bind(wx.EVT_BUTTON, lambda e: self.preview.fit())
            controls.Add(fit)
            preview_box.Add(controls, 0, wx.EXPAND | wx.BOTTOM, 6)
            preview_box.Add(self.preview, 1, wx.EXPAND)
            body = wx.BoxSizer(wx.HORIZONTAL)
            self.table.SetMinSize((260, 200))
            body.Add(self.table, 4, wx.EXPAND | wx.RIGHT, 10)
            body.Add(preview_box, 5, wx.EXPAND)
            root.Add(body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
            file_row = wx.BoxSizer(wx.HORIZONTAL)
            for label, method in (('Save recorded template…', self.on_save),
                                  ('Load recorded template…', self.on_load)):
                button = wx.Button(self, label=label)
                button.Bind(wx.EVT_BUTTON, method)
                file_row.Add(button, 0, wx.RIGHT, 7)
            root.Add(file_row, 0, wx.ALL, 10)
            self.status = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.status.SetMinSize((-1, 105))
            root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            self.SetSizer(root)
            self.record_btn.Enable(native_call is not None)
            self.scan_btn.Enable(native_call is not None)
            self.message('Select the master group in PCB Editor and click Record.'
                         if native_call is not None else
                         'Open the board through the native bridge to capture placement.')

        def message(self, text):
            self.status.SetValue(str(text))

        def error(self, exc):
            self.apply_btn.Enable(self.template is not None and self.call is not None)
            self.message(str(exc))
            wx.MessageBox(str(exc), 'Layout Clone', wx.OK | wx.ICON_WARNING, self)

        def on_record(self, _event):
            try:
                snap = self.call('layout_clone_capture',
                                 mode=assets.MODES[self.clone_mode.GetSelection()],
                                 include_graphics=self.include_graphics.GetValue(),
                                 scope=('selection', 'hierarchy')[self.scope.GetSelection()],
                                 parent_levels=self.parent_levels.GetValue())
                _validate_snapshot(snap)
                self.template = snap
                self.target = None
                self.plan = None
                self.overrides = {}
                self.anchor = None
                self.table.DeleteAllItems()
                self.anchor_choice.Clear()
                self.apply_btn.Enable(self.call is not None)
                self._update_preview()
                self.message(f'Recorded {len(snap["items"])} selected footprints; '
                             f'assets: {snap.get("assets", {}).get("counts", {})}. '
                             f"Scope: {snap.get('scope', 'selection')}. "
                             'Now select a DIFFERENT group or sheet instance in KiCad '
                             'and click Apply. '
                             'Sheet scope captures internal-net routing automatically; '
                             'select shared-net routes and graphics explicitly. '
                             'No table-row selection is required.')
            except Exception as exc:
                self.error(exc)

        def on_scan(self, _event):
            if self.template is None:
                self.error('Record or load a source placement first.')
                return
            try:
                result = self.call('layout_clone_target',
                                  scope=self.template.get('scope', 'selection'),
                                  parent_levels=self.template.get('parent_levels', 0))
                self.target = result['snapshot']
                self.copper_by_ref = result['copper_by_ref']
                self.overrides.clear()
                self.anchor = None
                self._render_plan()
            except Exception as exc:
                self.error(exc)

        def _render_plan(self):
            if self.template is None or self.target is None:
                return
            self.plan = make_plan(self.template, self.target,
                                  self.overrides, self.anchor,
                                  accept_value_changes=self.allow_values.GetValue(),
                                  allow_partial=self.allow_partial.GetValue())
            self.plan = assets.plan_options(
                self.template, self.target, self.plan,
                assets.MODES[self.clone_mode.GetSelection()], self.include_graphics.GetValue())
            rows = self.plan['pairs']
            self.copper = sum(self.copper_by_ref.get(p['target'], 0) for p in rows)
            self.table.Freeze()
            try:
                self.table.DeleteAllItems()
                for p in rows:
                    row = self.table.InsertItem(self.table.GetItemCount(), p['source'])
                    for col, txt in enumerate((p['target'], p['status'], str(p['score']),
                                               f'{p["x"]:.4f} / {p["y"]:.4f}',
                                               f'{p["angle"]:.1f}°'), start=1):
                        self.table.SetItem(row, col, txt)
                sources = [p['source'] for p in rows]
                self.anchor_choice.Clear()
                self.anchor_choice.AppendItems(sources)
                if self.plan['anchor'] in sources:
                    self.anchor_choice.SetSelection(sources.index(self.plan['anchor']))
            finally:
                self.table.Thaw()
            issues = list(self.plan['issues'])
            if self.copper:
                issues.append(f'{self.copper} local routed-copper segments touch target pads. '
                              'Unroute them before applying.')
            self.apply_btn.Enable(self.template is not None and self.call is not None)
            details = (f'{len(rows)} matched / {len(self.template["items"])} recorded; '
                       f'anchor: {self.plan["anchor"]}; '
                       f'offset: {self.plan["delta"]}\n')
            details += (f'Clone mode: {self.clone_mode.GetStringSelection()}; '
                        f'recorded assets: {self.template.get("assets", {}).get("counts", {})}\n')
            notices = list(self.plan.get('warnings', []))
            if self.plan['missing'] and self.allow_partial.GetValue():
                notices.append('Partial: missing ' + ', '.join(self.plan['missing']))
            if self.plan['extra'] and self.allow_partial.GetValue():
                notices.append('Untouched extras: ' + ', '.join(self.plan['extra']))
            if self.plan['value_differences'] and self.allow_values.GetValue():
                notices.append('Accepted value changes: ' +
                               ', '.join(self.plan['value_differences']))
            if notices:
                details += 'REVIEWED EXCEPTIONS: ' + '; '.join(notices) + '\n'
            self.message(details + ('Ready: apply to matched target footprints.'
                                    if not issues else 'Resolve before applying:\n- ' +
                                    '\n- '.join(issues)))
            self._update_preview()

        def _update_preview(self):
            from .layout_clone_preview import make_scene
            try:
                if self.template:
                    recorded = self.template.get('assets', {})
                    if 'preview' not in recorded and recorded.get('native_board'):
                        recorded['preview'] = assets.preview_from_native(recorded['native_board'])
                scene = make_scene(self.template, self.target, self.plan,
                                   assets.MODES[self.clone_mode.GetSelection()],
                                   self.include_graphics.GetValue(), self.preview_before.GetValue())
                notice = ('Proposed result - Apply runs safety checks' if self.plan and
                          self.plan['can_apply'] and not self.copper else
                          'Preview blocked - see issues below' if self.plan else
                          'Recorded source - select target, then Preview')
                self.preview.set_scene(scene, notice)
            except Exception as exc:
                self.preview.set_scene([], 'Preview unavailable: ' + str(exc))

        def on_preview_option(self, _event):
            self.preview.layer = self.preview_layer.GetStringSelection()
            self._update_preview()

        def on_anchor(self, _event):
            if self.anchor_choice.GetSelection() == wx.NOT_FOUND:
                return
            self.anchor = self.anchor_choice.GetStringSelection()
            try:
                self._render_plan()
            except Exception as exc:
                self.error(exc)

        def on_override(self, _event):
            row = self.table.GetFirstSelected()
            if self.target is None or self.template is None:
                self.on_scan(None)
                if self.target is None or self.template is None:
                    return
            if row < 0:
                refs = [s['ref'] for s in self.template['items']]
                with wx.SingleChoiceDialog(self, 'Choose the source component to edit:',
                                           'Optional match override', refs) as dialog:
                    if dialog.ShowModal() != wx.ID_OK:
                        return
                    source_ref = dialog.GetStringSelection()
            else:
                source_ref = self.table.GetItemText(row)
            source = next(s for s in self.template['items'] if s['ref'] == source_ref)
            choices = [d['ref'] for d in self.target['items']
                       if geometry_key(source) == geometry_key(d) and
                       d['ref'] not in {v for k, v in self.overrides.items()
                                        if k != source_ref}]
            if not choices:
                self.error('No physically compatible unassigned target footprints.')
                return
            with wx.SingleChoiceDialog(self, f'Choose equivalent for {source_ref}:',
                                       'Manual component assignment', choices) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                choice = dialog.GetStringSelection()
            self.overrides[source_ref] = choice
            try:
                self._render_plan()
            except Exception as exc:
                self.error(exc)

        def on_option(self, _event):
            try:
                self._render_plan()
                self._update_preview()
            except Exception as exc:
                self.error(exc)

        def on_reset(self, _event):
            self.overrides.clear()
            try:
                self._render_plan()
            except Exception as exc:
                self.error(exc)

        def on_apply(self, _event):
            if self.template is None:
                self.error('Record the source layout first, then select the target group.')
                return
            try:
                # Apply uses the current KiCad selection, never a selected table row.
                fresh = self.call('layout_clone_target',
                                  scope=self.template.get('scope', 'selection'),
                                  parent_levels=self.template.get('parent_levels', 0))
                old_ids = {p['id'] for p in self.target['items']} if self.target else set()
                new_ids = {p['id'] for p in fresh['snapshot']['items']}
                if old_ids != new_ids:
                    self.overrides.clear()
                    self.anchor = None
                self.target = fresh['snapshot']
                self.copper_by_ref = fresh['copper_by_ref']
                self._render_plan()
                if not self.plan['can_apply'] or self.copper:
                    self.message('Cannot apply this selection:\n' + self.status.GetValue())
                    return
                result = self.call('layout_clone_apply', template=self.template,
                                   expected_target=self.target,
                                   overrides=self.overrides, anchor=self.plan['anchor'],
                                   accept_value_changes=self.allow_values.GetValue(),
                                   allow_partial=self.allow_partial.GetValue(),
                                   mode=assets.MODES[self.clone_mode.GetSelection()],
                                   include_graphics=self.include_graphics.GetValue())
                self.apply_btn.Enable(self.call is not None)
                self.target = None
                self.plan = None
                self.preview.notice = 'Applied result - use KiCad Undo to revert'
                self.preview.Refresh()
                self.message(f'Applied {result["moved"]} footprints and '
                             f'{result.get("cloned_assets", 0)} layout assets. '
                             'Use KiCad Edit > Undo to revert; run DRC before routing.')
            except Exception as exc:
                self.error(exc)

        def on_save(self, _event):
            if self.template is None:
                self.error('Record a placement first.')
                return
            with wx.FileDialog(self, 'Save placement template', wildcard='JSON (*.json)|*.json',
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                try:
                    Path(dialog.GetPath()).write_text(
                        json.dumps(self.template, indent=2, ensure_ascii=False),
                        encoding='utf-8')
                    self.message('Placement template saved: ' + dialog.GetPath())
                except Exception as exc:
                    self.error(exc)

        def on_load(self, _event):
            with wx.FileDialog(self, 'Load placement template', wildcard='JSON (*.json)|*.json',
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                try:
                    snap = json.loads(Path(dialog.GetPath()).read_text(encoding='utf-8'))
                    _validate_snapshot(snap)
                    self.template = snap
                    self.target = None
                    self.plan = None
                    self.overrides.clear()
                    self.anchor = None
                    self.anchor_choice.Clear()
                    self.table.DeleteAllItems()
                    self.apply_btn.Enable(self.call is not None)
                    self._update_preview()
                    self.message(f'Loaded {len(snap["items"])} recorded parts. '
                                 'Select the target group in KiCad and click Apply.')
                except Exception as exc:
                    self.error(exc)

    return LayoutCloneTab()


if __name__ == '__main__':
    print('TraceForge Layout Clone is an integration module, not a standalone GUI.')
    print('Open the Layout Clone tab in TraceForge.')
