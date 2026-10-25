"""Read-only content signature on explicit focus/tab checks, never periodic polling."""
import hashlib

import pcbnew


def signature(board):
    rows = []
    for item in board.GetTracks():
        p, q = item.GetStart(), item.GetEnd()
        rows.append((item.m_Uuid.AsString(), item.GetNetCode(), item.GetLayer(),
                     p.x, p.y, q.x, q.y,
                     item.GetWidth(pcbnew.F_Cu) if isinstance(item, pcbnew.PCB_VIA)
                     else item.GetWidth(), item.GetLength(),
                     item.GetDrillValue() if isinstance(item, pcbnew.PCB_VIA) else 0,
                     str(item.GetLayerSet().FmtHex())))
    for fp in board.GetFootprints():
        p = fp.GetPosition()
        rows.append((fp.m_Uuid.AsString(), fp.GetReference(), fp.GetValue(), p.x, p.y,
                     fp.GetOrientationDegrees(), fp.GetLayer()))
        for pad in fp.Pads():
            p, size = pad.GetPosition(), pad.GetSize()
            rows.append((pad.m_Uuid.AsString(), pad.GetNumber(), pad.GetNetCode(), p.x, p.y,
                         size.x, size.y, pad.GetOrientationDegrees(),
                         str(pad.GetLayerSet().FmtHex())))
    for item in list(board.Zones()) + list(board.Drawings()):
        box = item.GetBoundingBox()
        rows.append((item.m_Uuid.AsString(), item.GetLayer(), box.GetX(), box.GetY(),
                     box.GetWidth(), box.GetHeight(), item.IsLocked()))
        if isinstance(item, pcbnew.ZONE):
            from signal_path_analyzer.stitching_native import contours

            poly = item.Outline()
            rows.append((item.GetNetCode(), item.GetFilledArea(), item.GetIsRuleArea(),
                         contours(poly)))
    ds = board.GetDesignSettings()
    rows.append((ds.GetViaSizeIndex(), ds.m_MinClearance, ds.m_ViasMinSize,
                 ds.m_MinThroughDrill, ds.m_CopperEdgeClearance,
                 tuple((v.m_Diameter, v.m_Drill) for v in ds.m_ViasDimensionsList)))
    for net in board.GetNetsByNetcode().values():
        cls = ds.m_NetSettings.GetEffectiveNetClass(net.GetNetname())
        rows.append((net.GetNetname(), cls.GetName(), cls.GetClearance(),
                     cls.GetViaDiameter(), cls.GetViaDrill()))
    digest = hashlib.sha256(repr(sorted(rows, key=repr)).encode('utf-8')).hexdigest()
    return f'{board.GetTimeStamp()}:{digest}'
