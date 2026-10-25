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
    if result.get('mode', 'dogbone') not in ('dogbone', 'via-in-pad'):
        raise ValueError('Choose Dogbone or explicit Via-in-pad mode.')
    if result.get('mode') == 'via-in-pad' and not result.get('allow_via_in_pad'):
        raise ValueError('Confirm that your fabrication process supports via-in-pad.')
    return result
