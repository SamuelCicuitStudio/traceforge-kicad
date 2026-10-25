"""Read selected live RF traces; keep source identity for stale-preview checks."""
from __future__ import annotations

import math

import pcbnew

from .trace_fence import order_path


def read_trace(board, identities=None):
    if identities is None:
        chosen = list(pcbnew.GetCurrentSelection())
        if not chosen or any(not isinstance(t, pcbnew.PCB_TRACK) or
                             isinstance(t, pcbnew.PCB_VIA) for t in chosen):
            raise ValueError('Select track segments/arcs of one RF trace in PCB Editor '
                             '(no vias or footprints), then Use selected trace.')
    else:
        live = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
        if any(k not in live for k in identities):
            raise ValueError('A source trace was deleted/rerouted. Select the new path again.')
        chosen = [live[k] for k in identities]
    if not chosen or len(chosen) > 500 or len({t.m_Uuid.AsString() for t in chosen}) != len(chosen):
        raise ValueError('Select between 1 and 500 distinct RF trace segments.')
    if any(isinstance(t, pcbnew.PCB_VIA) for t in chosen):
        raise ValueError('A trace fence must follow track segments, not vias.')
    if len({t.GetNetname() for t in chosen}) != 1 or len({t.GetLayer() for t in chosen}) != 1:
        raise ValueError('Select one signal net on one copper layer.')
    if not chosen[0].GetNetname():
        raise ValueError('Assign the source trace to a signal net first.')

    def point(p):
        return [p.x / 1e6, p.y / 1e6]

    paths = []
    for item in chosen:
        a, b = point(item.GetStart()), point(item.GetEnd())
        if isinstance(item, pcbnew.PCB_ARC):
            c, mid = point(item.GetCenter()), point(item.GetMid())
            radius = math.dist(a, c)
            start = math.atan2(a[1] - c[1], a[0] - c[0])
            end = math.atan2(b[1] - c[1], b[0] - c[0])
            middle = math.atan2(mid[1] - c[1], mid[0] - c[0])
            sweep = (end - start) % math.tau
            if (middle - start) % math.tau > sweep:
                sweep -= math.tau
            step = min(math.radians(5), 2 * math.acos(max(-1, 1 - .002 / max(radius, .002))))
            count = max(2, math.ceil(abs(sweep) / max(step, 1e-6)))
            if count > 2000:
                raise ValueError('Selected arc is too large; select a shorter RF path.')
            points = [a] + [[c[0] + radius * math.cos(start + sweep * i / count),
                             c[1] + radius * math.sin(start + sweep * i / count)]
                            for i in range(1, count)] + [b]
        else:
            points = [a, b]
        paths.append(points)
    points = order_path(paths)
    if len(points) > 5000:
        raise ValueError('Selected path is too complex; select a shorter trace.')
    return dict(kind='trace', tracks=sorted(t.m_Uuid.AsString() for t in chosen), points=points,
                net=chosen[0].GetNetname(), layer=pcbnew.LayerName(chosen[0].GetLayer()),
                width_mm=max(t.GetWidth() for t in chosen) / 1e6,
                widths=sorted((t.m_Uuid.AsString(), t.GetWidth()) for t in chosen))
