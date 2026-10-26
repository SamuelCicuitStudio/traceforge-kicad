"""Independent BGA dogbone geometry; no third-party routing code or dependencies."""
from __future__ import annotations

import fnmatch
import math
from bisect import bisect_left
from collections import Counter


def clusters(values, tolerance=.002):
    result = []
    for value in sorted(values):
        if not result or value - result[-1] > tolerance:
            result.append(value)
    return result


def grid_info(pads):
    if len(pads) < 9:
        raise ValueError('Select an array with at least nine SMD pads.')
    axes = [clusters(p['local'][i] for p in pads) for i in (0, 1)]
    for axis in axes:
        if len(axis) < 3:
            raise ValueError('This footprint is not a two-dimensional ball grid.')
    occupied = {tuple(axis_index(axes[i], p['local'][i]) for i in (0, 1))
                for p in pads}
    if len(occupied) != len(pads):
        raise ValueError('Pads overlap at a grid location; check the selected footprint.')
    counts = [Counter(site[i] for site in occupied) for i in (0, 1)]
    if any(count < 2 for axis in counts for count in axis.values()):
        raise ValueError('An isolated pad row or column was found; this is not a '
                         'rectangular BGA array. Check for a displaced pad.')
    if not any((x + 1, y) in occupied and (x, y + 1) in occupied and
               (x + 1, y + 1) in occupied for x, y in occupied):
        raise ValueError('No rectangular ball cells detected; staggered/perimeter packages '
                         'need a different fanout strategy.')
    row_x = [[p['local'][0] for p in pads
              if axis_index(axes[1], p['local'][1]) == row]
             for row in range(len(axes[1]))]
    col_y = [[p['local'][1] for p in pads
              if axis_index(axes[0], p['local'][0]) == col]
             for col in range(len(axes[0]))]
    row_x = [sorted(row) for row in row_x]
    col_y = [sorted(col) for col in col_y]
    gaps = [[b - a for values in bands for a, b in zip(values, values[1:])]
            for bands in (row_x, col_y)]
    pitches = [min(gap) for gap in gaps]
    if min(pitches) < .05:
        raise ValueError('Two pads in the same row or column are less than 0.05 mm '
                         'apart; check the selected footprint.')
    return dict(pitch_x=pitches[0], pitch_y=pitches[1], rows=len(axes[1]),
                columns=len(axes[0]), axes=axes, row_x=row_x, col_y=col_y,
                bounds=[axes[0][0], axes[0][-1], axes[1][0], axes[1][-1]],
                variable_pitch=any(max(gap) - min(gap) > .002 for gap in gaps),
                center=[(a[0] + a[-1]) / 2 for a in axes])


def axis_index(axis, value):
    """Find a pad's coordinate band without assuming a global pitch."""
    index = bisect_left(axis, value)
    if index == len(axis) or (index and abs(axis[index - 1] - value) <
                              abs(axis[index] - value)):
        index -= 1
    return index


def half_gaps(pad, grid):
    """Local left/right/top/bottom half-spacing, extrapolated at array edges."""
    x, y = pad['local']
    row = axis_index(grid['axes'][1], y)
    col = axis_index(grid['axes'][0], x)
    result = []
    for axis, value in ((grid['row_x'][row], x), (grid['col_y'][col], y)):
        index = axis_index(axis, value)
        before = axis[index] - axis[index - 1] if index else axis[1] - axis[0]
        after = axis[index + 1] - axis[index] if index + 1 < len(axis) else before
        result.append((before, after))
    local_min = min(gap for pair in result for gap in pair)
    # A hollow-center row can have a multi-millimetre gap. Keep the dogbone
    # close to its source instead of drawing a long diagonal across the void.
    return [tuple(min(gap, 2 * local_min) / 2 for gap in pair) for pair in result]


def candidates(pad, grid, offset_x=0, offset_y=0):
    x, y = pad['local']
    sx = 1 if x >= grid['center'][0] else -1
    sy = 1 if y >= grid['center'][1] else -1
    gaps_x, gaps_y = half_gaps(pad, grid)
    return [[x + a * (offset_x or gaps_x[0 if a < 0 else 1]),
             y + b * (offset_y or gaps_y[0 if b < 0 else 1])]
            for a, b in
            ((sx, sy), (-sx, sy), (sx, -sy), (-sx, -sy))]


def world(point, position, angle):
    angle = math.radians(angle)
    x, y = point
    return [position[0] + x * math.cos(angle) + y * math.sin(angle),
            position[1] - x * math.sin(angle) + y * math.cos(angle)]


def matches(name, include='*', exclude=''):
    include = [p.strip() for p in include.split(',') if p.strip()]
    exclude = [p.strip() for p in exclude.split(',') if p.strip()]
    return (any(fnmatch.fnmatchcase(name, p) for p in include or ['*']) and
            not any(fnmatch.fnmatchcase(name, p) for p in exclude))


def validate(values):
    result = dict(values)
    for key in ('diameter', 'drill', 'width', 'clearance', 'offset_x', 'offset_y', 'edge'):
        try:
            result[key] = float(values[key])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'Enter a valid {key} in mm.') from exc
        if not math.isfinite(result[key]) or result[key] < 0:
            raise ValueError(f'{key} must be finite and non-negative.')
    if result['drill'] <= 0 or result['diameter'] <= result['drill'] or result['width'] <= 0:
        raise ValueError('Use a positive track width/drill and a via diameter '
                         'larger than its drill.')
    if result.get('mode', 'dogbone') not in ('dogbone', 'via-in-pad', 'auto-escape'):
        raise ValueError('Choose Dogbone, Auto escape, or explicit Via-in-pad mode.')
    if result.get('mode') == 'via-in-pad' and not result.get('allow_via_in_pad'):
        raise ValueError('Confirm that your fabrication process supports via-in-pad.')
    return result


def fit_guidance(data, values):
    """Explain nominal BGA fit before the live obstacle/DRC preview."""
    grid, limits = data['grid'], data['limits']
    selected = [p for p in data['pads'] if p['net'] and
                matches(p['net'], values.get('include', '*'), values.get('exclude', '')) and
                matches(p['number'], values.get('pads', '*'))]
    pads = selected or data['pads']
    rules = [data.get('net_rules', {}).get(p['net'], {}) for p in pads]
    width = max([values['width']] + ([r.get('width', 0) for r in rules]
                                   if values.get('netclass_width', True) else []))
    clearance = max([values['clearance'], limits['clearance']] +
                    [r.get('clearance', 0) for r in rules])
    via_sizes = ([tuple((r.get('diameter', values['diameter']),
                         r.get('drill', values['drill']))) for r in rules]
                 if values.get('preset') == 'netclass' or
                 (values.get('preset') == 'active' and data.get('active') == 0) else
                 [(values['diameter'], values['drill'])])
    if not via_sizes:
        via_sizes = [(values['diameter'], values['drill'])]
    minimum_diameter = max(limits['diameter'],
                           max(drill for _, drill in via_sizes) + 2 * limits['annulus'])
    local = [half_gaps(p, grid) for p in pads]
    minimum_channel = min(2 * min(pair[side] for pair in gaps for side in (0, 1)) -
                          max(p['size'][axis] for p in data['pads'])
                          for axis, gaps in enumerate(zip(*local)))
    channel_width = minimum_channel - 2 * clearance
    radius = max(math.hypot(*p['size']) / 2 for p in data['pads'])
    via_limit = min(max(2 * (math.dist(p['local'], site) - radius - clearance)
                        for site in candidates(p, grid)) for p in pads)
    reasons = []
    if width + 1e-9 < limits['width']:
        reasons.append(f'Track {width:.3f} mm is below board minimum '
                       f'{limits["width"]:.3f} mm.')
    if any(drill + 1e-9 < limits['drill'] or diameter + 1e-9 < minimum_diameter or
           (diameter - drill) / 2 + 1e-9 < limits['annulus']
           for diameter, drill in via_sizes):
        reasons.append('Via/drill/annular ring violates board minimums: '
                       f'via >= {minimum_diameter:.3f} mm, drill >= '
                       f'{limits["drill"]:.3f} mm, annulus >= '
                       f'{limits["annulus"]:.3f} mm.')
    if values.get('mode') != 'via-in-pad' and max(d for d, _ in via_sizes) > via_limit + 1e-9:
        reasons.append(f'Interior diagonal gap fits about {max(0, via_limit):.3f} mm '
                       f'via; selected size reaches {max(d for d, _ in via_sizes):.3f} mm.')
    if width > channel_width + 1e-9:
        reasons.append(f'Straight inter-ball channel fits about '
                       f'{max(0, channel_width):.3f} mm track; '
                       f'effective width is {width:.3f} mm.')
    return dict(ok=not reasons, reasons=reasons, selected=len(selected),
                effective_width=width, effective_clearance=clearance,
                channel_width=max(0, channel_width), via_gap_limit=max(0, via_limit),
                minimum_diameter=minimum_diameter)
