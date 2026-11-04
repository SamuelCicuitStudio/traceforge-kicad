"""Rotate selected PCB items inside KiCad's undoable board-edit action."""
from __future__ import annotations

import math

import pcbnew

from .stitching_native import transaction


def _angle(value):
    try:
        angle = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Enter a rotation angle in degrees, such as 45 or -45.') from exc
    if not math.isfinite(angle) or abs(angle) > 360:
        raise ValueError('Rotation must be a finite angle between -360 and 360 degrees.')
    if angle == 0:
        raise ValueError('Enter a nonzero rotation angle.')
    return angle


def _selected():
    items = list(pcbnew.GetCurrentSelection())
    if not items:
        raise ValueError('Select a component in PCB Editor first.')
    supported = (pcbnew.FOOTPRINT,)
    unsupported = [type(item).__name__ for item in items if not isinstance(item, supported)]
    if unsupported:
        raise ValueError('TraceForge exact-angle rotation currently supports components only. '
                         'For shapes and zones, set KiCad’s rotation step in Preferences > '
                         'PCB Editor > Editing Options, then use R. '
                         f'Unsupported selected item: {unsupported[0]}.')
    if any(item.IsLocked() for item in items):
        raise ValueError('Unlock the selected PCB items before rotating them.')
    return items


def apply(board, angle):
    """Apply an angle about each selected footprint's anchor."""
    degrees = _angle(angle)
    items = _selected()
    counts = dict(components=0, shapes=0, zones=0)
    rotation = pcbnew.EDA_ANGLE(degrees, pcbnew.DEGREES_T)

    def rotate(live):
        # KiCad returns a fresh SWIG wrapper for the same live board when its
        # undoable ActionPlugin runs. The transaction already checks the board
        # filename, so Python object identity is not a valid board check here.
        for item in items:
            item.Rotate(item.GetPosition(), rotation)
            counts['components'] += 1
        if counts['components']:
            live.BuildConnectivity()
        pcbnew.Refresh()
        return dict(counts, angle=degrees)

    return transaction(board, rotate)


def dispatch(board, operation, payload):
    if operation == 'rotate_apply':
        return apply(board, payload.get('angle'))
    raise ValueError(f'Unknown rotation operation: {operation}')
