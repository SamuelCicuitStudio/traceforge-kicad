"""Live-connectivity fixture checks; no user board is loaded or written."""
import importlib.util
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pcbnew as k  # noqa: E402

from signal_path_analyzer import unrouted_native as tool  # noqa: E402

board = k.BOARD()
board.SetFileName('unrouted-fixture.kicad_pcb')
nets = {}
for name in ['PARTIAL', 'EMPTY', 'POUR']:
    net = k.NETINFO_ITEM(board, name)
    board.Add(net)
    nets[name] = net


def pad(ref, x, y, net):
    fp = k.FOOTPRINT(board)
    fp.SetReference(ref)
    p = k.PAD(fp)
    p.SetNumber('1')
    p.SetAttribute(k.PAD_ATTRIB_SMD)
    layers = k.LSET()
    layers.AddLayer(k.F_Cu)
    p.SetLayerSet(layers)
    p.SetSize(k.VECTOR2I(k.FromMM(1), k.FromMM(1)))
    p.SetPosition(k.VECTOR2I(k.FromMM(x), k.FromMM(y)))
    p.SetNet(nets[net])
    fp.Add(p)
    board.Add(fp)
    return p


def track(a, b, net):
    t = k.PCB_TRACK(board)
    t.SetStart(k.VECTOR2I(*(k.FromMM(v) for v in a)))
    t.SetEnd(k.VECTOR2I(*(k.FromMM(v) for v in b)))
    t.SetWidth(k.FromMM(.25))
    t.SetLayer(k.F_Cu)
    t.SetNet(nets[net])
    board.Add(t)
    return t


pad('J1', 10, 10, 'PARTIAL')
pad('J2', 30, 10, 'PARTIAL')
track([10, 10], [20, 10], 'PARTIAL')
for i in range(3):
    pad('J'+str(i+3), i*10+10, 20, 'EMPTY')
result = tool.scan(board)
assert len(result['rows']) == 3, result
partial = next(r for r in result['rows'] if r['net'] == 'PARTIAL')
assert partial['status'] == 'Remaining gap' and partial['gap_mm'] == 10
assert all(r['status'] == 'Unrouted net' for r in result['rows'] if r['net'] == 'EMPTY')
assert not tool.focus(board, dict(id=partial['id']))['resolved']
track([20, 10], [30, 10], 'PARTIAL')
assert tool.focus(board, dict(id=partial['id']))['resolved']
assert len(tool.scan(board)['rows']) == 2
# One zone parent with two filled islands must not falsely join their pads.
pad('Z1', 10, 40, 'POUR')
pad('Z2', 30, 40, 'POUR')
zone = k.ZONE(board)
zone.SetLayer(k.F_Cu)
zone.SetNet(nets['POUR'])
zone.Outline().NewOutline()
for x, y in [(5, 35), (35, 35), (35, 45), (5, 45)]:
    zone.Outline().Append(k.FromMM(x), k.FromMM(y))
filled = k.SHAPE_POLY_SET()
for x in [10, 30]:
    filled.NewOutline()
    for a, b in [(x-2, 38), (x+2, 38), (x+2, 42), (x-2, 42)]:
        filled.Append(k.FromMM(a), k.FromMM(b))
zone.SetFilledPolysList(k.F_Cu, filled)
zone.SetIsFilled(True)
zone.SetNeedRefill(False)
board.Add(zone)
result = tool.scan(board)
assert len([r for r in result['rows'] if r['net'] == 'POUR']) == 1, result
assert zone.GetFilledPolysList(k.F_Cu).OutlineCount() == 2
print('PASS: partial routes, pad-only nets, resolved-gap detection and separate zone islands')

# Dispatch must centre zoom on gap anchors, not the full extent of a long track.

spec = importlib.util.spec_from_file_location('unrouted_server_fixture',
    Path(__file__).resolve().parents[1] / 'native_bridge/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
seen = {}


def highlight(board, items, nets, refs, ids):
    seen['ids'] = ids
    return [item for item in items if item.m_Uuid.AsString() in ids]


def zoom(board, items, force=False):
    seen['points'] = [[k.ToMM(p.GetPosition().x), k.ToMM(p.GetPosition().y)] for p in items]
    assert force
    return True


server._highlights = types.SimpleNamespace(apply=highlight)
server.zoom_to_items = zoom
row = next(r for r in result['rows'] if r['net'] == 'EMPTY')
old_refresh = k.Refresh
count_before = len(list(board.GetFootprints()))+len(list(board.GetTracks()))
k.Refresh = lambda: None
try:
    focused = server.dispatch(board, 'unrouted_focus', dict(id=row['id']))
    assert focused['zoomed']
    assert seen['points'] == [row['a']['position'], row['b']['position']]
    assert seen['ids'] == {row['a']['id'], row['b']['id']}
    assert count_before == len(list(board.GetFootprints()))+len(list(board.GetTracks()))
finally:
    k.Refresh = old_refresh
print('PASS: bridge highlights exact endpoints and fits temporary gap anchors; no items added')
