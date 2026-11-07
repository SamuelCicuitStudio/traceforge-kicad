"""Replace KiCad's real selection, never expand a via filter into its nets."""
from __future__ import annotations

import pcbnew


def identity(item):
    return item.m_Uuid.AsString()


def live_items(board):
    # Include drawings, zones, groups, footprint children and previous selections.
    # BOARD_ITEM_SET is not iterable in KiCad 10's SWIG bindings.
    native = (list(board.GetTracks()) + list(board.Drawings()) + list(board.Zones()) +
              list(board.Groups()) + list(board.GetFootprints()))
    items = {identity(item): item for item in native}
    for fp in board.GetFootprints():
        for item in list(fp.Pads()) + list(fp.GraphicalItems()) + list(fp.GetFields()):
            items[identity(item)] = item
    for item in pcbnew.GetCurrentSelection():
        items[identity(item)] = item
    return items


def replace(board, identities):
    wanted = set(identities)
    items = live_items(board)
    if any(key not in items or not isinstance(items[key], pcbnew.PCB_VIA) for key in wanted):
        raise ValueError('Via selection changed. Refresh the filters and select again.')
    # Remove old parents/groups before adding children/members. KiCad removes
    # child selection when it deselects a parent, so a single refresh can lose it.
    for item in items.values():
        item.ClearSelected()
        item.ClearBrightened()
    pcbnew.Refresh()
    for key in wanted:
        items[key].SetSelected()
    # KiCad 10 RebuildAndRefresh updates the native selection container from flags.
    pcbnew.Refresh()
    selected = {identity(item) for item in pcbnew.GetCurrentSelection()}
    if selected != wanted:
        for item in live_items(board).values():
            item.ClearSelected()
        pcbnew.Refresh()
        raise RuntimeError('KiCad did not select exactly the matching vias. '
                           'Selection was cleared; no successful count is reported.')
    return [items[key] for key in sorted(wanted)]


def dim_other_copper(board, identities):
    """Activate renderer dimming without highlighting every GND/signal net.

    KiCad's SWIG interface exposes net highlighting, not an item-dimming mask.
    A temporary selection of an existing unconnected board item enables its
    neutral net-0 highlight; the actual via selection is restored immediately.
    No geometry/net codes are modified. Net-0 copper can remain undimmed.
    """
    # Prefer the board outline/keepouts. Pads are footprint children and SWIG's
    # Refresh does not reliably add them to the native selection container.
    top_level = list(board.Drawings()) + list(board.Zones()) + list(board.GetTracks())
    seeds = [item for item in top_level
             if isinstance(item, pcbnew.BOARD_CONNECTED_ITEM) and
             not isinstance(item, pcbnew.FOOTPRINT) and item.GetNetCode() == 0]
    if not identities or not seeds:
        return False
    from .net_focus import run_exact as run
    from .net_focus import shortcut

    shortcut('highlightNet')
    shortcut('clearHighlight')
    items = live_items(board)
    for item in items.values():
        item.ClearSelected()
    pcbnew.Refresh()
    seeds[0].SetSelected()
    pcbnew.Refresh()
    try:
        if {identity(item) for item in pcbnew.GetCurrentSelection()} != {identity(seeds[0])}:
            raise RuntimeError('KiCad did not synchronize the dimming selection.')
        if not run('highlightNet'):
            raise RuntimeError('KiCad did not handle its native highlight action.')
        if not board.IsHighLightNetON():
            raise RuntimeError('KiCad did not activate renderer dimming.')
    finally:
        replace(board, identities)
    return True
