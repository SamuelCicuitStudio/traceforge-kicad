"""Conservative, board-wide copper track corner planning (coordinates in KiCad IU)."""
from __future__ import annotations

from collections import defaultdict
from math import acos, hypot, isfinite, sin, tan

MIN_RADIUS_IU = 50_000  # 0.05 mm: smaller arcs are visually insignificant.


def _distance(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


def _point(a, direction, distance):
    return [round(a[0] + direction[0] * distance),
            round(a[1] + direction[1] * distance)]


def refit(entry, radius_iu):
    """Return a corner with fresh tangent and midpoint geometry at this radius."""
    vertex, rays, inner = entry['point'], entry['rays'], entry['inner']
    setback = radius_iu / tan(inner / 2)
    tangent = [_point(vertex, ray, setback) for ray in rays]
    bisector = (rays[0][0] + rays[1][0], rays[0][1] + rays[1][1])
    magnitude = hypot(*bisector)
    center_distance = radius_iu / sin(inner / 2)
    center = (vertex[0] + bisector[0] / magnitude * center_distance,
              vertex[1] + bisector[1] / magnitude * center_distance)
    inward = (vertex[0] - center[0], vertex[1] - center[1])
    inward_length = hypot(*inward)
    return {**entry, 'radius_iu': radius_iu, 'setback': setback,
            'tangent': tangent,
            'mid': _point(center, (inward[0] / inward_length,
                                   inward[1] / inward_length), radius_iu)}


def plan(tracks, protected_points, radius_iu, selected_ids=None, adaptive=True):
    """Return eligible arc corners and explicit skipped-corner reasons.

    Only degree-two, same-net/layer/width straight-track junctions qualify.
    Caller supplies pad/via/arc contact points and all straight tracks.
    """
    if not isfinite(radius_iu) or radius_iu <= 0:
        raise ValueError('Radius must be greater than zero.')
    selected_ids = None if selected_ids is None else set(selected_ids)
    nodes = defaultdict(list)
    for row in tracks:
        for end in ('start', 'end'):
            nodes[(row['layer'], tuple(row[end]))].append((row, end))
    candidates, skipped = [], []
    for (layer, vertex), members in nodes.items():
        if len(members) < 2:
            continue
        if selected_ids is not None and not any(
                row['id'] in selected_ids for row, _ in members):
            continue
        names = sorted({row['name'] for row, _ in members})
        entry = {'layer': layer, 'point': list(vertex),
                 'nets': names, 'ids': [row['id'] for row, _ in members]}
        if len(members) != 2:
            entry['reason'] = 'Branch or overlapping junction'
        elif (layer, vertex) in protected_points:
            entry['reason'] = 'Pad, via, or existing arc at corner'
        elif any(row['protected'] for row, _ in members):
            entry['reason'] = 'Locked, grouped, or managed track'
        elif names[0] == '' or len(names) != 1 or any(row['net'] <= 0 for row, _ in members):
            entry['reason'] = 'Different or missing net'
        elif members[0][0]['width'] != members[1][0]['width']:
            entry['reason'] = 'Different track widths'
        else:
            rays, lengths = [], []
            for row, end in members:
                far = row['end' if end == 'start' else 'start']
                length = _distance(vertex, far)
                if length == 0:
                    break
                rays.append(((far[0] - vertex[0]) / length,
                             (far[1] - vertex[1]) / length))
                lengths.append(length)
            if len(rays) != 2:
                entry['reason'] = 'Zero-length track'
            else:
                inner = acos(max(-1.0, min(1.0, rays[0][0] * rays[1][0] +
                                              rays[0][1] * rays[1][1])))
                if inner < 0.087 or inner > 3.054:  # ~5 to 175 degrees
                    entry['reason'] = 'Corner too sharp or nearly straight'
                else:
                    entry.update(ends=[end for _, end in members],
                                 rays=rays, inner=inner, lengths=lengths,
                                 width=members[0][0]['width'], net=members[0][0]['net'])
                    bisector = (rays[0][0] + rays[1][0], rays[0][1] + rays[1][1])
                    magnitude = hypot(*bisector)
                    if magnitude < 1e-8 or sin(inner / 2) < 1e-8:
                        entry['reason'] = 'Invalid corner geometry'
                    else:
                        max_radius = (min(lengths) - entry['width'] / 2 - 1_000) * tan(inner / 2)
                        chosen_radius = min(radius_iu, max_radius) if adaptive else radius_iu
                        if chosen_radius < MIN_RADIUS_IU or chosen_radius > max_radius:
                            entry['reason'] = 'Radius does not fit adjacent track'
                        else:
                            entry = refit(entry, chosen_radius)
                            if entry['tangent'][0] == entry['tangent'][1]:
                                entry['reason'] = 'Rounded geometry collapses to a point'
        if 'reason' in entry:
            skipped.append(entry)
        else:
            candidates.append(entry)

    # A segment can be filleted at both ends, but its two setbacks must not meet.
    used = defaultdict(float)
    accepted = []
    for entry in sorted(candidates, key=lambda item: (item['layer'], item['point'])):
        available = min(length - used[identity] - entry['width'] / 2 - 1_000
                        for identity, length in zip(entry['ids'], entry['lengths']))
        max_radius = available * tan(entry['inner'] / 2)
        if entry['radius_iu'] > max_radius:
            if not adaptive or max_radius < MIN_RADIUS_IU:
                skipped.append({**entry, 'reason': 'Not enough room after neighboring fillet'})
                continue
            entry = refit(entry, max_radius)
        accepted.append(entry)
        for identity in entry['ids']:
            used[identity] += entry['setback']
    return accepted, skipped
