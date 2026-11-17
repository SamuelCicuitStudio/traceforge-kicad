"""Exercise differential/single-ended rows and raw selection keys in real wx controls."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wx

from signal_path_analyzer.chains import (
    ChainDef,
    Config,
    GroupDef,
    NetDelay,
    NetGeometry,
    TrackSeg,
    evaluate,
)
from signal_path_analyzer.hub_ui import Tools, TraceForgePanel

p = ChainDef("RAM", "DQS_P", ("/p",), pair="DQS_N")
n = ChainDef("RAM", "DQS_N", ("/n",), pair="DQS_P")
dq = ChainDef("RAM", "DQ0", ("/dq0",))
cfg = Config([GroupDef("RAM", (p, n, dq), skew_ps=3.5, pair_skew_ps=0.6)])
geo = {key: NetGeometry("DDR", [TrackSeg("F.Cu", 1)]) for key in ["/p", "/n", "/dq0"]}
results = evaluate(cfg, {key: NetDelay(100, 0, 0, True) for key in geo}, geo)
app = wx.App(False)
TraceForgePanel.register_shortcuts = lambda *a: None
frame = TraceForgePanel(Tools(lambda: results, *([lambda *a: None] * 6)))
try:
    frame.tools.routing_configuration = lambda: dict(
        stackup='4 layers | F.Cu 0.035 mm | dielectric 0.18 mm Er=4.2 | In1.Cu',
        rows=[['USB90', 'USB', 'DIFF', '90', 'F.Cu', 'In1.Cu', '0.2520', '0.2000',
               'Saved profile geometry']], note='Last saved board/project')
    frame.busy = True
    frame.on_refresh()
    frame.busy = False
    assert frame.routing_geometry.GetItemCount() == 1
    assert frame.routing_geometry.GetItemText(0, 6) == '0.2520'
    assert frame.routing_geometry.GetItemText(0, 7) == '0.2000'
    assert '0.18 mm' in frame.stackup_display.GetLabel()
    frame.overlay.Stop()
    frame.activity_timer.Stop()
    frame.results = results
    frame.render()
    assert frame.tree.GetItemText(frame.rows["RAM", "DQS_P"]) == "[DIFF] DQS_P (mate: DQS_N)"
    assert frame.tree.GetItemText(frame.rows["RAM", "DQ0"]) == "[SE] DQ0"
    frame.tree.SelectItem(frame.rows["RAM", "DQS_P"])
    assert frame.selected() == ("RAM", "DQS_P")
    frame.render()
    assert frame.selected() == ("RAM", "DQS_P")
    print(
        
            "PASS: hidden native wx table renders DIFF versus SE, "
            "preserves real chain IDs and refresh selection"
        
    )
finally:
    frame.worker.shutdown(wait=False, cancel_futures=True)
    frame.Destroy()
