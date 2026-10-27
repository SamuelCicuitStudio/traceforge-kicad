"""Fit existing via centers to a regular array inside their current bounds."""
from __future__ import annotations

from math import ceil


def _assignment(costs):
    """Minimum total squared movement, with deterministic ties."""
    n = len(costs)
    potentials_row, potentials_col = [0] * (n + 1), [0] * (n + 1)
    matched, predecessor = [0] * (n + 1), [0] * (n + 1)
    for row in range(1, n + 1):
        matched[0] = row
        minimum = [float('inf')] * (n + 1)
        used = [False] * (n + 1)
        col = 0
        while True:
            used[col] = True
            active = matched[col]
            delta, next_col = float('inf'), 0
            for candidate in range(1, n + 1):
                if used[candidate]:
                    continue
                value = (costs[active - 1][candidate - 1] - potentials_row[active] -
                         potentials_col[candidate])
                if value < minimum[candidate]:
                    minimum[candidate] = value
                    predecessor[candidate] = col
                if minimum[candidate] < delta:
                    delta, next_col = minimum[candidate], candidate
            for candidate in range(n + 1):
                if used[candidate]:
                    potentials_row[matched[candidate]] += delta
                    potentials_col[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            col = next_col
            if matched[col] == 0:
                break
        while col:
            previous = predecessor[col]
            matched[col] = matched[previous]
            col = previous
    answer = [0] * n
    for col in range(1, n + 1):
        answer[matched[col] - 1] = col - 1
    return answer


def arrange(points, fixed_axis, fixed_count):
    """Return targets for (UUID, x_nm, y_nm) vias; no new vias are created."""
    if not points or len(points) > 64:
        raise ValueError('Select between 1 and 64 vias in PCB Editor.')
    if fixed_axis == 'auto':
        return infer(points)
    if fixed_axis not in ('rows', 'columns'):
        raise ValueError('Choose a fixed row or column count.')
    if not isinstance(fixed_count, int) or not 1 <= fixed_count <= len(points):
        raise ValueError('The fixed count must be between 1 and the number of selected vias.')
    points = sorted(points, key=lambda p: p[0])
    xs, ys = [p[1] for p in points], [p[2] for p in points]
    bounds = (min(xs), min(ys), max(xs), max(ys))
    rows = fixed_count if fixed_axis == 'rows' else ceil(len(points) / fixed_count)
    columns = fixed_count if fixed_axis == 'columns' else ceil(len(points) / fixed_count)
    if columns > 1 and bounds[0] == bounds[2]:
        raise ValueError('Selected vias have no horizontal span for multiple columns.')
    if rows > 1 and bounds[1] == bounds[3]:
        raise ValueError('Selected vias have no vertical span for multiple rows.')
    pitch_x = (bounds[2] - bounds[0]) / (columns - 1) if columns > 1 else 0
    pitch_y = (bounds[3] - bounds[1]) / (rows - 1) if rows > 1 else 0
    if (columns > 1 and pitch_x < 1) or (rows > 1 and pitch_y < 1):
        raise ValueError('The selected rectangle is too small for that many rows or columns.')
    slots = []
    if fixed_axis == 'columns':
        for row in range(rows):
            width = min(columns, len(points) - len(slots))
            start = (columns - width) / 2
            for col in range(width):
                slots.append((round(bounds[0] + (start + col) * pitch_x),
                              round((bounds[1] + bounds[3]) / 2 if rows == 1 else
                                    bounds[1] + row * pitch_y)))
    else:
        for col in range(columns):
            height = min(rows, len(points) - len(slots))
            start = (rows - height) / 2
            for row in range(height):
                slots.append((round((bounds[0] + bounds[2]) / 2 if columns == 1 else
                                    bounds[0] + col * pitch_x),
                              round(bounds[1] + (start + row) * pitch_y)))
    if len(set(slots)) != len(points):
        raise ValueError('The fitted grid has overlapping centers.')
    costs = [[(p[1] - x) ** 2 + (p[2] - y) ** 2 for x, y in slots] for p in points]
    assigned = _assignment(costs)
    return dict(rows=rows, columns=columns, bounds=bounds,
                pitch_x_nm=pitch_x, pitch_y_nm=pitch_y,
                moves=[dict(uuid=p[0], old=(p[1], p[2]), new=slots[assigned[i]])
                       for i, p in enumerate(points)])


def infer(points):
    """Choose the existing row/column topology with the least via movement."""
    candidates = []
    for axis in ('columns', 'rows'):
        for count in range(1, len(points) + 1):
            try:
                layout = arrange(points, axis, count)
            except ValueError:
                continue
            movement = sum((row['old'][0] - row['new'][0]) ** 2 +
                           (row['old'][1] - row['new'][1]) ** 2
                           for row in layout['moves'])
            unused = layout['rows'] * layout['columns'] - len(points)
            candidates.append((movement, unused, abs(layout['rows'] - layout['columns']),
                               layout))
    if not candidates:
        raise ValueError('The selected via centers cannot form a grid inside their bounds.')
    result = min(candidates, key=lambda item: item[:3])[3]
    result['inferred'] = True
    return result
