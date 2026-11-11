"""Find standalone through vias for manual stitching cleanup."""
from __future__ import annotations

from collections import defaultdict

import pcbnew

from .cancellation import check_payload
from .stitching_native import uid


def scan(board, payload):
    """List through vias without direct track, pad, via or copper-drawing contact.

    Filled-zone contact is reported separately; a zone-only via can be valid
    stitching and must not be described as electrically unconnected.
    """
    layers = list(board.GetEnabledLayers().CuStack())
    vias = [item for item in board.GetTracks()
            if isinstance(item, pcbnew.PCB_VIA) and
            item.GetViaType() == pcbnew.VIATYPE_THROUGH]
    copper = [item for item in board.GetTracks()
              if not isinstance(item, pcbnew.PCB_VIA)]
    copper.extend(vias)
    for footprint in board.GetFootprints():
        copper.extend(footprint.Pads())
        copper.extend(item for item in footprint.GraphicalItems()
                      if any(item.IsOnLayer(layer) for layer in layers))
    copper.extend(item for item in board.Drawings()
                  if any(item.IsOnLayer(layer) for layer in layers))

    cell = 5_000_000
    buckets = defaultdict(list)
    for item in copper:
        check_payload(payload)
        active = [layer for layer in layers if item.IsOnLayer(layer)]
        if not active:
            continue
        box = item.GetBoundingBox()
        record = (item, active)
        for x in range(box.GetX() // cell,
                       (box.GetX() + box.GetWidth()) // cell + 1):
            for y in range(box.GetY() // cell,
                           (box.GetY() + box.GetHeight()) // cell + 1):
                buckets[(x, y)].append(record)

    standalone = []
    for via in vias:
        check_payload(payload)
        position = via.GetPosition()
        via_layers = set(via.GetLayerSet().CuStack())
        via_shapes = {layer: via.GetEffectiveShape(layer) for layer in via_layers}
        touching = False
        for item, active in buckets.get((position.x // cell, position.y // cell), ()):
            if item is via:
                continue
            if not item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                continue
            for layer in via_layers.intersection(active):
                shape = item.GetEffectiveShape(layer)
                if shape and via_shapes[layer].Collide(shape):
                    touching = True
                    break
            if touching:
                break
        if not touching:
            standalone.append(via)

    if standalone:
        board.BuildConnectivity()
        connectivity = board.GetConnectivity()
    rows = []
    for via in standalone:
        check_payload(payload)
        connected = [pcbnew.LayerName(layer) for layer in via.GetLayerSet().CuStack()
                     if connectivity.IsConnectedOnLayer(via, layer)]
        if payload.get('unstitched_only') and len(connected) >= 2:
            continue
        position = via.GetPosition()
        rows.append(dict(uuid=uid(via), net=str(via.GetNetname()),
                         x_mm=position.x / 1e6, y_mm=position.y / 1e6,
                         drill_mm=via.GetDrillValue() / 1e6,
                         connected_layers=connected, locked=via.IsLocked(),
                         free=via.GetIsFree()))
    rows.sort(key=lambda row: (row['net'], row['x_mm'], row['y_mm']))
    return dict(count=len(rows), vias=rows, unstitched_only=bool(payload.get('unstitched_only')))
