"""Check changed drill envelopes only; no copper-routing DRC or zone refill."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pcbnew

from .cancellation import check_file
from .stitching_native import fits, outline, uid
from .stitching_protection_native import box_shape
from .via_drill import rule_bounds


def limit_signature(board):
    ds = board.GetDesignSettings()
    return tuple(getattr(ds, field) for field in (
        'm_MinThroughDrill', 'm_ViasMinAnnularWidth', 'm_HoleClearance',
        'm_HoleToHoleMin', 'm_CopperEdgeClearance'))


def check_holes(board, chosen, drill, cancel_file=None):
    check_file(cancel_file)
    ds = board.GetDesignSettings()
    rules = Path(board.GetFileName()).with_suffix('.kicad_dru')
    try:
        bounds = rule_bounds(rules.read_text(encoding='utf-8') if rules.exists() else '')
        boundary = outline(board)
    except ValueError as error:
        return None, str(error)
    minimum = max(ds.m_MinThroughDrill, bounds.get('hole_size', {}).get('min', 0))
    maximum = bounds.get('hole_size', {}).get('max', 1e12)
    ring = max(ds.m_ViasMinAnnularWidth, bounds.get('annular_width', {}).get('min', 0))
    ring_max = bounds.get('annular_width', {}).get('max', 1e12)
    physical = bounds.get('physical_hole_clearance', {}).get('min', 0)
    hole_gap = max(ds.m_HoleClearance, bounds.get('hole_clearance', {}).get('min', 0), physical)
    drill_gap = max(ds.m_HoleToHoleMin, bounds.get('hole_to_hole', {}).get('min', 0), physical)
    edge_gap = max(ds.m_CopperEdgeClearance, bounds.get('edge_clearance', {}).get('min', 0))
    layers = list(board.GetEnabledLayers().CuStack())
    obstacles = list(board.GetTracks())
    for fp in board.GetFootprints():
        obstacles.extend(fp.Pads())
        obstacles.extend(g for g in fp.GraphicalItems() if g.GetLayer() in layers)
    obstacles.extend(g for g in board.Drawings() if g.GetLayer() in layers)
    # Build a local spatial index once, not an all-pairs/full-routing scan.
    buckets = defaultdict(list)
    cell = 5_000_000

    def add(shape, gap, identity, net, kind):
        box = shape.BBox()
        margin = (drill+1)//2 + gap
        row = (shape, gap, identity, net, kind)
        for iy in range((box.GetY()-margin)//cell, (box.GetBottom()+margin)//cell+1):
            for ix in range((box.GetX()-margin)//cell, (box.GetRight()+margin)//cell+1):
                buckets[ix, iy].append(row)

    for item in obstacles:
        check_file(cancel_file)
        identity = uid(item)
        net = item.GetNetCode() if isinstance(item, pcbnew.BOARD_CONNECTED_ITEM) else -1
        if isinstance(item, (pcbnew.PAD, pcbnew.PCB_VIA)) and item.HasDrilledHole():
            hole = (pcbnew.SHAPE_CIRCLE(item.GetPosition(), (drill+1)//2)
                    if identity in chosen else item.GetEffectiveHoleShape())
            if hole:
                add(hole, drill_gap, identity, net, 'hole-to-hole clearance')
        for layer in layers:
            if item.IsOnLayer(layer):
                shape = (item.GetEffectiveShape(layer) if isinstance(
                    item, (pcbnew.PAD, pcbnew.PCB_TRACK, pcbnew.PCB_SHAPE)) else
                    box_shape(item.GetBoundingBox()))
                if shape:
                    add(shape, hole_gap, identity, net, 'hole-to-copper clearance')
    foreign = []
    for zone in board.Zones():
        check_file(cancel_file)
        if zone.GetIsRuleArea():
            continue  # Its via prohibition is unchanged when only the drill changes.
        if not zone.IsFilled() or zone.NeedRefill():
            return None, 'Stale zone fills require the full DRC path.'
        for layer in zone.GetLayerSet().CuStack():
            foreign.append((zone.GetFilledPolysList(layer), zone.GetNetCode()))
    checks = {}
    for identity, via in chosen.items():
        check_file(cancel_file)
        if any(via.IsBackdrilledOrPostMachined(layer) for layer in layers):
            return None, 'Backdrilled vias require full DRC.'
        annulus = (via.GetWidth(via.TopLayer())-drill)/2
        point = via.GetPosition()
        circle = pcbnew.SHAPE_CIRCLE(point, (drill+1)//2)
        reason = None
        if not minimum <= drill <= maximum:
            reason = 'Drill outside project/custom hole-size limits.'
        elif not ring <= annulus <= ring_max:
            reason = f'Annular ring {annulus/1e6:.3f} mm violates project/custom limits.'
        elif not fits(boundary, point, (drill+1)//2 + edge_gap):
            reason = 'Drilled hole too close to board edge/cutout.'
        else:
            for shape, gap, other, net, kind in buckets[point.x//cell, point.y//cell]:
                if other == identity or (kind == 'hole-to-copper clearance' and
                                         net == via.GetNetCode() and net > 0):
                    continue
                if shape.Collide(circle, gap):
                    reason = kind + ': ' + other
                    break
            if reason is None and any((net != via.GetNetCode() or net <= 0) and
                                      poly.Collide(circle, hole_gap)
                                      for poly, net in foreign):
                reason = 'hole-to-zone copper clearance'
        checks[identity] = reason
    return checks, None
