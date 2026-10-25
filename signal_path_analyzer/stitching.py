"""Geometry and persistent ownership records shared by stitching UI and native helper."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

MAX_CANDIDATES = 5000


def distance_to_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    denom = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / denom)) if denom else 0
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def edges(poly):
    return zip(poly, poly[1:] + poly[:1])


def inside(p, poly, margin=0):
    """Require a point and its margin circle to fit inside a simple polygon."""
    hit = False
    for a, b in edges(poly):
        if distance_to_segment(p, a, b) < max(margin, 1e-9):
            return False
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
                hit = not hit
    return hit


def polygon(points):
    poly = [tuple(float(v) for v in p) for p in points]
    if len(poly) > 1 and poly[0] == poly[-1]:
        poly.pop()
    if len(poly) < 3 or len(set(poly)) != len(poly):
        raise ValueError('A region needs at least three distinct vertices.')
    if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in poly):
        raise ValueError('Region coordinates must be finite X/Y pairs.')
    area = sum(a[0] * b[1] - a[1] * b[0] for a, b in edges(poly))
    if abs(area) < 1e-8:
        raise ValueError('The region has zero area.')

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    segments = list(edges(poly))
    for i, (a, b) in enumerate(segments):
        for j in range(i + 1, len(segments)):
            if j == i + 1 or (i == 0 and j == len(segments) - 1):
                continue
            c, d = segments[j]
            if cross(a, b, c) * cross(a, b, d) <= 0 and cross(c, d, a) * cross(c, d, b) <= 0:
                if (max(min(a[0], b[0]), min(c[0], d[0])) <=
                    min(max(a[0], b[0]), max(c[0], d[0])) and
                    max(min(a[1], b[1]), min(c[1], d[1])) <=
                        min(max(a[1], b[1]), max(c[1], d[1]))):
                    raise ValueError('The polygon crosses or touches itself.')
    return poly


def settings(values):
    result = dict(values)
    for key in ('diameter', 'drill', 'pitch_x', 'pitch_y', 'offset_x', 'offset_y',
                'boundary', 'edge'):
        try:
            result[key] = float(values[key])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f'Enter a valid {key.replace("_", " ")} in mm.') from exc
        if not math.isfinite(result[key]):
            raise ValueError(f'{key} must be finite.')
    if result['diameter'] <= result['drill'] or result['drill'] <= 0:
        raise ValueError('Via diameter must be larger than its positive drill diameter.')
    if min(result['pitch_x'], result['pitch_y']) <= result['diameter']:
        raise ValueError('Spacing is center-to-center and must exceed the via diameter.')
    if min(result['edge'], result['boundary']) < 0:
        raise ValueError('Setbacks cannot be negative.')
    if not result.get('net'):
        raise ValueError('Choose a stitching net.')
    result['pattern'] = values.get('pattern', 'symmetric')
    if result['pattern'] not in ('symmetric', 'staggered'):
        raise ValueError('Choose Symmetric or Staggered placement.')
    return result


def grid(bounds, values):
    x0, y0, x1, y1 = bounds
    sx, sy = values['pitch_x'], values['pitch_y']
    ox, oy = values['offset_x'], values['offset_y']
    iy0, iy1 = math.ceil((y0 - oy) / sy), math.floor((y1 - oy) / sy)
    if iy1 - iy0 + 1 > MAX_CANDIDATES:
        raise ValueError('Region has too many grid rows; increase spacing or use a smaller region.')
    staggered = values.get('pattern') == 'staggered'
    result = []
    # Row parity is anchored to the persistent board grid, not the region's first row.
    for j in range(iy0, iy1 + 1):
        shift = sx / 2 if staggered and j % 2 else 0
        ix0, ix1 = math.ceil((x0 - ox - shift) / sx), math.floor((x1 - ox - shift) / sx)
        if len(result) + max(ix1 - ix0 + 1, 0) > MAX_CANDIDATES:
            raise ValueError(f'Region exceeds {MAX_CANDIDATES} grid locations; increase spacing '
                             'or use a smaller region.')
        result.extend((i * sx + ox + shift, j * sy + oy) for i in range(ix0, ix1 + 1))
    return result


def store_path(board_file):
    return Path(board_file).with_suffix('.traceforge-stitching.json')


def load_store(board_file):
    path = store_path(board_file)
    if not path.exists():
        return {'version': 1, 'records': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('records'), dict):
        raise ValueError(f'Unrecognized stitching metadata: {path.name}')
    return data


def save_store(board_file, data):
    path = store_path(board_file)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)
