"""Offset open trace paths for RF via fencing, independent of KiCad bindings."""
from __future__ import annotations

import math


def order_path(segments, tolerance=.000002):
    """Order endpoint-connected segments; reject branches, loops and disconnected paths."""
    def key(p):
        return tuple(round(v / tolerance) for v in p)

    graph = {}
    for i, points in enumerate(segments):
        if len(points) < 2 or key(points[0]) == key(points[-1]):
            raise ValueError('Select a nonzero open trace path.')
        for p in (points[0], points[-1]):
            graph.setdefault(key(p), []).append(i)
    if any(len(v) > 2 for v in graph.values()):
        raise ValueError('Selected traces branch. Select only the intended RF path.')
    ends = sorted(k for k, v in graph.items() if len(v) == 1)
    if len(ends) != 2:
        raise ValueError('Select one connected open trace path, without branches or loops.')
    current, used, result = ends[0], set(), []
    while True:
        remaining = [i for i in graph[current] if i not in used]
        if not remaining:
            break
        i = remaining[0]
        used.add(i)
        points = segments[i]
        if key(points[0]) != current:
            points = list(reversed(points))
        result.extend(points if not result else points[1:])
        current = key(points[-1])
    if len(used) != len(segments):
        raise ValueError('Selected traces are disconnected. Select one continuous RF path.')
    return result


def offset_path(points, distance, side):
    if not math.isfinite(distance) or distance <= 0 or side not in (-1, 1):
        raise ValueError('Fence offset must be positive and side must be left/right.')
    normals = []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-8:
            raise ValueError('Trace contains a zero-length segment.')
        # Board Y increases downward: negative Y is visibly left for a rightward path.
        normals.append((side * dy / length, -side * dx / length))
    result = []
    for i, p in enumerate(points):
        if i == 0:
            nx, ny = normals[0]
        elif i == len(points) - 1:
            nx, ny = normals[-1]
        else:
            a, b = normals[i - 1], normals[i]
            denominator = 1 + a[0] * b[0] + a[1] * b[1]
            if denominator < .15:
                raise ValueError('Trace reverses too sharply. '
                                 'Select a smaller path around this bend.')
            nx, ny = (a[0] + b[0]) / denominator, (a[1] + b[1]) / denominator
        result.append([p[0] + nx * distance, p[1] + ny * distance])
    return result


def sample_open(points, spacing):
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('Fence spacing must be positive.')
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    length = sum(lengths)
    if not length:
        raise ValueError('Trace path has zero length.')
    count = max(1, math.ceil(length / spacing))
    if count > 4999:
        raise ValueError('Trace fence exceeds the candidate limit; increase spacing.')
    result, index, consumed = [], 0, 0.0
    for i in range(count + 1):
        station = length * i / count
        while index < len(lengths) - 1 and station > consumed + lengths[index]:
            consumed += lengths[index]
            index += 1
        factor = (station - consumed) / lengths[index]
        a, b = points[index:index + 2]
        result.append(([a[0] + factor * (b[0] - a[0]),
                        a[1] + factor * (b[1] - a[1])], station))
    return result, length


def open_gap(length, stations):
    if not stations:
        return length
    stations = sorted(stations)
    return max([stations[0], length - stations[-1]] +
               [b - a for a, b in zip(stations, stations[1:])])
