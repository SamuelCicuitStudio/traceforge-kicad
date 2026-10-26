"""Bounded, deterministic route proposals from a BGA breakout via to its pad-field edge."""
from __future__ import annotations


def paired_net(name, names):
    """Recognize a differential pair only when its partner net actually exists."""
    partners = []
    for positive, negative in (('_P', '_N'), ('+', '-'), ('_DP', '_DN')):
        if name.endswith(positive):
            partners.append(name[:-len(positive)] + negative)
        if name.endswith(negative):
            partners.append(name[:-len(negative)] + positive)
    return any(partner in names for partner in partners)


def edge_paths(start, grid, margin=None):
    """Yield short straight/dogleg paths in footprint-local millimetres."""
    px, py = grid['pitch_x'], grid['pitch_y']
    margin = margin if margin is not None else max(px, py) * .6
    min_x, max_x, min_y, max_y = grid['bounds']
    left, right = min_x - margin, max_x + margin
    top, bottom = min_y - margin, max_y + margin
    x, y = start
    directions = sorted((
        (abs(x-left), 'left', left), (abs(right-x), 'right', right),
        (abs(y-top), 'top', top), (abs(bottom-y), 'bottom', bottom)))
    for _, side, boundary in directions:
        if side in ('left', 'right'):
            for shift in (0, -py / 2, py / 2):
                endpoint = [boundary, y + shift]
                route = [list(start)]
                if shift:
                    route.append([x, y + shift])
                route.append(endpoint)
                yield route
        else:
            for shift in (0, -px / 2, px / 2):
                endpoint = [x + shift, boundary]
                route = [list(start)]
                if shift:
                    route.append([x + shift, y])
                route.append(endpoint)
                yield route
