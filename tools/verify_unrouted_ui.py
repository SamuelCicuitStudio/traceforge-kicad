"""Hidden wx navigation and filtering checks; no live board access."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wx  # noqa: E402

from signal_path_analyzer.unrouted_ui import UnroutedPanel  # noqa: E402

app = wx.App(False)
frame = wx.Frame(None)
calls = []
rows = [dict(id=str(i), net='NET'+str(i), netclass='DIGITAL', status='Remaining gap',
             gap_mm=i+.25, a=dict(label='U1.1', position=[0, 0]),
             b=dict(label='J1.'+str(i), position=[i+1, 0])) for i in range(3)]


class Host:
    colors = dict(pending='#999999', error='#ff0000')

    def submit_stitching(self, fn, done, page):
        done(fn())


def native(operation, **payload):
    calls.append((operation, payload))
    if operation == 'unrouted_scan':
        return dict(rows=rows, nets=3, native_airwires=3)
    if operation == 'unrouted_focus':
        return dict(resolved=False, zoomed=True)
    return dict(cleared=True)


panel = UnroutedPanel(frame, Host(), native)
try:
    panel.on_refresh()
    assert panel.table.GetItemCount() == 3
    panel.step(1)
    app.Yield()
    assert calls[-1] == ('unrouted_focus', dict(id='0', whole_net=False))
    panel.step(1)
    app.Yield()
    assert calls[-1][1]['id'] == '1'
    panel.step(-1)
    app.Yield()
    assert calls[-1][1]['id'] == '0'
    panel.filter.SetValue('NET2')
    panel.fill()
    assert panel.table.GetItemCount() == 1
    panel.whole_net.SetValue(True)
    panel.step(1)
    app.Yield()
    assert calls[-1] == ('unrouted_focus', dict(id='2', whole_net=True))
    panel.on_clear()
    assert calls[-1][0] == 'unrouted_clear'
    print('PASS: unrouted UI scan, click/next/previous focus, filtering and whole-net selection')
finally:
    frame.Destroy()
