"""Native wx regression: Apply matches automatically without a selected table row."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wx  # noqa: E402

from signal_path_analyzer.traceforge_layout_clone import create_tab  # noqa: E402


def snapshot(prefix, x):
    return dict(format=1, board='fixture.kicad_pcb', items=[dict(
        id=prefix+str(i), ref=prefix+str(i), footprint='Local:C0402', value='100n',
        layer='F.Cu', x=x+i*2, y=10, angle=0, locked=False,
        pads=[dict(number=str(p), shape=0, type=0, size=[1, 1], local=[p, 0],
                   local_angle=0, net=n, pad_id=prefix+str(i)+str(p))
              for p, n in [(1, 'VCC'), (2, 'GND')]]) for i in [1, 2]])


app = wx.App(False)
frame = wx.Frame(None)
source = snapshot('C', 0)
target = snapshot('T', 40)
calls = []


def native(operation, **payload):
    calls.append(operation)
    if operation == 'layout_clone_capture':
        return copy.deepcopy(source)
    if operation == 'layout_clone_target':
        return dict(snapshot=copy.deepcopy(target), copper_by_ref={})
    if operation == 'layout_clone_apply':
        assert payload['overrides'] == {}
        assert payload['expected_target'] == target
        return dict(moved=2, cloned_assets=0)
    raise AssertionError(operation)


tab = create_tab(frame, native)
try:
    tab.on_record(None)
    assert tab.apply_btn.IsEnabled()
    assert tab.table.GetFirstSelected() == -1
    tab.on_apply(None)
    assert calls == ['layout_clone_capture', 'layout_clone_target', 'layout_clone_apply']
    assert tab.table.GetFirstSelected() == -1
    assert 'Applied 2 footprints' in tab.status.GetValue()
    assert tab.apply_btn.IsEnabled()  # ready for another selected target group
    target = snapshot('NEXT', 80)
    tab.on_apply(None)
    assert calls[-2:] == ['layout_clone_target', 'layout_clone_apply']
    source['assets'] = dict(counts=dict(tracks=1, vias=1), preview=[
        dict(kind='copper', points=[[3, 10], [6, 10]], width=.25, layer='F.Cu'),
        dict(kind='copper', points=[[6, 10], [6, 14], [8, 14]], width=.25, layer='B.Cu'),
        dict(kind='via', points=[[6, 10]], width=.6, drill=.3, layer='via')])
    tab.on_record(None)
    tab.clone_mode.SetSelection(2)
    tab.on_scan(None)
    assert any(p['kind'] == 'copper' for p in tab.preview.scene)
    assert any(p['kind'] == 'via' for p in tab.preview.scene)
    assert any(p.get('ghost') for p in tab.preview.scene)
    bitmap = wx.Bitmap(900, 520)
    dc = wx.MemoryDC(bitmap)
    tab.preview.draw(dc, wx.Size(900, 520))
    dc.SelectObject(wx.NullBitmap)
    destination = Path(__file__).resolve().parents[1] / 'build/layout-clone-preview.png'
    bitmap.SaveFile(str(destination), wx.BITMAP_TYPE_PNG)
    tab.preview_layer.SetSelection(1)
    tab.on_preview_option(None)
    assert not any(p['kind'] == 'copper' and p['layer'] == 'B.Cu'
                   for p in tab.preview.visible())
    print('PASS: automatic Apply; read-only preview, before/after, tracks/vias, '
          'layer filter and paint')
finally:
    frame.Destroy()
