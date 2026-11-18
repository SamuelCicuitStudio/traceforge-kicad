"""Hidden wx selected-reference preview and apply controls, without a live PCB."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wx  # noqa: E402

from signal_path_analyzer.component_update_ui import ComponentUpdatePanel  # noqa: E402

app = wx.App(False)
frame = wx.Frame(None, size=(940, 680))
calls = []
pad = dict(number='1', local=[0, 0], local_angle=0, size=[1, 1])
row = dict(reference='R1', footprint='Local:R', status='ready', pads=1,
           checked_contacts=1, models='existing models preserved',
           old=dict(pads=[pad]), new=dict(pads=[pad]))


class Host:
    dark = False
    refresh_policy = type('Policy', (), dict(invalidate=lambda self: None))()

    def submit_stitching(self, function, done, page):
        done(function())


def native(operation, **payload):
    calls.append((operation, payload))
    if operation == 'component_update_preview':
        return dict(token='preview', rows=[row], ready=True)
    return dict(updated=['R1'], note='Placement and routing retained.')


panel = ComponentUpdatePanel(frame, Host(), native)
try:
    panel.on_preview()
    assert panel.table.GetItemCount() == 1 and panel.apply.IsEnabled()
    panel.canvas.row = row
    frame.Show()
    panel.canvas.Refresh()
    app.Yield()
    panel.on_apply()
    assert calls[-1] == ('component_update_apply', dict(token='preview'))
    assert not panel.apply.IsEnabled()
    panel.on_preview()
    panel.models.SetValue(True)
    panel.invalidate()
    assert panel.token is None and not panel.apply.IsEnabled()
    print('PASS: selected-reference preview, pad comparison paint, explicit apply and invalidation')
finally:
    frame.Destroy()
