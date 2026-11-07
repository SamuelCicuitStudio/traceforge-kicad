"""Assembly/fiducial exclusion shapes, shared by stitching and RF fencing."""
from __future__ import annotations

import pcbnew

from .stitching_protection import protection_kind


def box_shape(box):
    poly = pcbnew.SHAPE_POLY_SET()
    poly.NewOutline()
    for x, y in ((box.GetX(), box.GetY()), (box.GetRight(), box.GetY()),
                 (box.GetRight(), box.GetBottom()), (box.GetX(), box.GetBottom())):
        poly.Append(x, y)
    return poly


def protection_shapes(board, values):
    """Return (shape, copper-edge margin, reason) in board coordinates.

    Through vias penetrate both sides. Protect both courtyards; do not treat
    optical or mechanical exclusion as belonging only to a copper net/layer.
    """
    guards = []
    component_gap = round(values['component_clearance'] * 1e6)
    for fp in board.GetFootprints():
        library = fp.GetFPID()
        library_id = str(library.GetLibNickname()) + ':' + str(library.GetLibItemName())
        kind = protection_kind(str(fp.GetReference()), str(fp.GetValue()),
                               library_id, values['protected_refs'])
        special = kind != 'component courtyard'
        if not special and not values['respect_courtyards']:
            continue
        gap = (round(values['critical_clearance'] * 1e6)
               if kind == 'critical footprint' else component_gap)
        if kind == 'fiducial optical area' and not any(
                pad.IsOnLayer(pcbnew.F_Cu) or pad.IsOnLayer(pcbnew.B_Cu) for pad in fp.Pads()):
            # Graphic-only optical markers have no copper pad to inflate below.
            gap = max(gap, round(values['fiducial_clearance'] * 1e6))
        reason = kind + ': ' + str(fp.GetReference())
        fp.BuildCourtyardCaches()
        courts = [fp.GetCourtyard(layer) for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd)]
        courts = [poly for poly in courts if poly.OutlineCount()]
        if courts:
            guards.extend((poly, gap, reason) for poly in courts)
        elif special or values['respect_courtyards']:
            # A missing courtyard must not make the footprint invisible. Exclude
            # its physical graphics/pads, without distant reference/value text.
            guards.append((box_shape(fp.GetBoundingBox(False, False)), gap, reason))
        if kind == 'fiducial optical area':
            fid_gap = round(values['fiducial_clearance'] * 1e6)
            for pad in fp.Pads():
                for copper, mask in ((pcbnew.F_Cu, pcbnew.F_Mask),
                                     (pcbnew.B_Cu, pcbnew.B_Mask)):
                    if not pad.IsOnLayer(copper):
                        continue
                    shape = pad.GetEffectiveShape(copper)
                    if shape:
                        # Protect the optical opening as well as pad copper.
                        expansion = max(0, pad.GetSolderMaskExpansion(mask))
                        guards.append((shape, max(fid_gap, expansion + component_gap), reason))
    return guards
