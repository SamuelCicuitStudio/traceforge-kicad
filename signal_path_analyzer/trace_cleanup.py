"""Conservative redundant-copper detection using exact integer geometry."""
from collections import defaultdict
from math import gcd, hypot


def analyze(rows):
    """Only remove copper fully covered by retained, identical-property copper.

    No snapping tolerance, via removal, branch pruning or partial-overlap fusion.
    Locked/grouped objects can cover other copper but are never removed.
    """
    lines, arcs = defaultdict(list), defaultdict(list)
    for row in rows:
        if row['net'] <= 0:
            continue  # Unassigned copper has no common electrical-net contract.
        base = (row['net'], row['layer'], row['width'], tuple(row['mask']))
        a, b = tuple(row['start']), tuple(row['end'])
        if row['kind'] == 'arc':
            arcs[base + (tuple(sorted((a, b))), tuple(row['mid']))].append(row)
            continue
        dx, dy = b[0] - a[0], b[1] - a[1]
        factor = gcd(dx, dy)
        if not factor:
            continue
        dx, dy = dx // factor, dy // factor
        if dx < 0 or (dx == 0 and dy < 0):
            dx, dy = -dx, -dy
        start, end = sorted((a[0] * dx + a[1] * dy, b[0] * dx + b[1] * dy))
        lines[base + (dx, dy, a[0] * dy - a[1] * dx)].append((start, end, row))
    redundant, partial, fusions = [], [], []

    def result(row, keep, reason):
        return dict(id=row['id'], net=row['name'], layer=row['layer'],
                    length_mm=row['length_mm'], reason=reason, keep=keep)

    for group in arcs.values():
        group.sort(key=lambda row: (not row['protected'], row['id']))
        keeper = group[0]
        for row in group[1:]:
            if not row['protected']:
                redundant.append(result(row, [keeper['id']], 'Duplicate arc'))
    for key, intervals in lines.items():
        if len(intervals) > 2000:
            raise ValueError('Too many collinear tracks for one cleanup preview. '
                             'Narrow the scan to an individual net.')
        intervals.sort(key=lambda entry: (not entry[2]['protected'],
                                          -(entry[1] - entry[0]), entry[2]['id']))
        retained = []
        for start, end, row in intervals:
            cursor, keep = start, []
            for left, right, other in sorted(retained, key=lambda entry: entry[0]):
                if left > cursor:
                    break
                if right > cursor:
                    cursor = right
                    keep.append(other['id'])
                if cursor >= end:
                    break
            if cursor >= end and not row['protected']:
                redundant.append(result(row, keep, 'Fully covered straight track'))
            else:
                retained.append((start, end, row))
        # Remaining overlaps need review; neither member is safe to delete whole.
        retained.sort(key=lambda entry: entry[0])
        for i, (start, end, row) in enumerate(retained):
            for left, right, other in retained[i + 1:]:
                if left >= end:
                    break
                if min(end, right) > max(start, left):
                    partial.append(result(row, [other['id']], 'Retained overlap: review'))
        # A component with a genuine partial overlap can be represented by one
        # continuous segment. Exact duplicates/containment use deletion above.
        ordered = sorted(intervals, key=lambda entry: (entry[0], entry[1]))
        components, component, edge = [], [], None
        for entry in ordered:
            if component and entry[0] >= edge:
                components.append(component)
                component = []
            component.append(entry)
            edge = max(edge, entry[1]) if edge is not None and len(component) > 1 else entry[1]
        if component:
            components.append(component)
        for component in components:
            if len(component) < 2 or any(row['protected'] for _, _, row in component):
                continue
            partial_overlap = any(
                a < c < b < d for a, b, _ in component for c, d, _ in component)
            if not partial_overlap:
                continue
            first = min(component, key=lambda entry: entry[0])
            last = max(component, key=lambda entry: entry[1])
            dx, dy = key[4:6]
            def at(entry, value, dx=dx, dy=dy):
                row = entry[2]
                return (row['start'] if row['start'][0] * dx + row['start'][1] * dy == value
                        else row['end'])
            begin, finish = at(first, first[0]), at(last, last[1])
            fusions.append(dict(ids=sorted(row['id'] for _, _, row in component),
                                net=first[2]['name'], layer=first[2]['layer'],
                                start=begin, end=finish,
                                saved_mm=sum(row['length_mm'] for _, _, row in component)
                                - hypot(finish[0]-begin[0],finish[1]-begin[1]) / 1e6))
    fused = {identity for item in fusions for identity in item['ids']}
    redundant = [row for row in redundant if row['id'] not in fused]
    partial = [row for row in partial if row['id'] not in fused]
    return dict(redundant=redundant, partial=partial, fusions=fusions,
                removed_length_mm=sum(row['length_mm'] for row in redundant))
