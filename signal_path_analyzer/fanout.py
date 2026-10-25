"""Independent BGA dogbone geometry; no third-party routing code or dependencies."""
from __future__ import annotations

import fnmatch
import math


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
    pitches = []
    for axis in axes:
        if len(axis) < 3:
            raise ValueError('This footprint is not a two-dimensional ball grid.')
        gaps = [b - a for a, b in zip(axis, axis[1:])]
        pitch = min(gaps)
        if pitch < .05 or any(abs(gap / pitch - round(gap / pitch)) > .02 for gap in gaps):
            raise ValueError('Irregular pad pitch: only regular rectangular '
                             'BGA grids are supported.')
        pitches.append(pitch)
    origin = [axis[0] for axis in axes]
    occupied = {(round((p['local'][0] - origin[0]) / pitches[0]),
                 round((p['local'][1] - origin[1]) / pitches[1])) for p in pads}
    if len(occupied) != len(pads):
        raise ValueError('Pads overlap at a grid location; select one regular BGA footprint.')
    if not any((x + 1, y) in occupied and (x, y + 1) in occupied and
               (x + 1, y + 1) in occupied for x, y in occupied):
        raise ValueError('No rectangular ball cells detected; staggered/perimeter packages '
                         'need a different fanout strategy.')
    return dict(pitch_x=pitches[0], pitch_y=pitches[1], rows=max(y for _, y in occupied) + 1,
                columns=max(x for x, _ in occupied) + 1,
                center=[(a[0] + a[-1]) / 2 for a in axes])


def candidates(pad, grid, offset_x=0, offset_y=0):
    dx = offset_x or grid['pitch_x'] / 2
    dy = offset_y or grid['pitch_y'] / 2
    x, y = pad['local']
    sx = 1 if x >= grid['center'][0] else -1
    sy = 1 if y >= grid['center'][1] else -1
    return [[x + dx * a, y + dy * b] for a, b in
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
    minimum_channel = min(grid['pitch_x'] - max(p['size'][0] for p in pads),
                          grid['pitch_y'] - max(p['size'][1] for p in pads))
    channel_width = minimum_channel - 2 * clearance
    radius = max(math.hypot(*p['size']) / 2 for p in pads)
    via_limit = 2 * (math.hypot(grid['pitch_x'] / 2, grid['pitch_y'] / 2)
                     - radius - clearance)
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
