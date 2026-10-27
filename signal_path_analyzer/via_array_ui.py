"""Visual editor panel for fitting selected existing vias into a grid."""
from __future__ import annotations

from math import hypot

import wx


class ViaArrayPreview(wx.Panel):
    """Show the actual and proposed via centers in the same bounding rectangle."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.SetMinSize((-1, 250))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))

    def show(self, result):
        self.result = result
        self.Refresh()

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        size = self.GetClientSize()
        self.render(dc, size.width, size.height)

    def render(self, dc, width, height):
        dc.SetBackground(wx.Brush('#19212D'))
        dc.Clear()
        if not self.result:
            dc.SetTextForeground(wx.Colour('#A8B4C7'))
            dc.DrawText('Select vias in PCB Editor, then click Read & preview selection.', 16, 16)
            return
        data = self.result
        x0, y0, x1, y1 = data['bounds_mm']
        span_x, span_y = max(x1 - x0, 0.001), max(y1 - y0, 0.001)
        gap = 12
        card_width = max(1, (width - 3 * gap) // 2)
        issue_ids = {identity for identity, _reason in data['issues']}
        for index, title in enumerate(('Current positions', 'Proposed array')):
            left = gap + index * (card_width + gap)
            box = wx.Rect(left, gap, card_width, max(1, height - 2 * gap))
            dc.SetPen(wx.Pen('#37475C', 1))
            dc.SetBrush(wx.Brush('#222C3A'))
            dc.DrawRoundedRectangle(box, 6)
            dc.SetTextForeground(wx.Colour('#E5EDF8'))
            dc.DrawText(title, left + 12, gap + 9)
            plot = wx.Rect(left + 32, gap + 40, max(1, card_width - 64),
                           max(1, height - 76))
            scale = min(plot.width / span_x, plot.height / span_y)
            draw_width, draw_height = (x1 - x0) * scale, (y1 - y0) * scale
            cx = plot.x + plot.width / 2
            cy = plot.y + plot.height / 2

            def screen(point, cx=cx, cy=cy, scale=scale):
                return (round(cx + (point[0] - (x0 + x1) / 2) * scale),
                        round(cy + (point[1] - (y0 + y1) / 2) * scale))

            dc.SetPen(wx.Pen('#607389', 1))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(round(cx - draw_width / 2) - 9,
                             round(cy - draw_height / 2) - 9,
                             round(draw_width) + 18, round(draw_height) + 18)
            if index:
                dc.SetPen(wx.Pen('#59758F', 1, wx.PENSTYLE_DOT))
                for col in range(data['columns']):
                    x = (x0 + x1) / 2 if data['columns'] == 1 else (
                        x0 + col * data['pitch_x_mm'])
                    px, _ = screen((x, y0))
                    dc.DrawLine(px, plot.y, px, plot.y + plot.height)
                for row in range(data['rows']):
                    y = (y0 + y1) / 2 if data['rows'] == 1 else (
                        y0 + row * data['pitch_y_mm'])
                    _, py = screen((x0, y))
                    dc.DrawLine(plot.x, py, plot.x + plot.width, py)
                dc.SetPen(wx.Pen('#6A809B', 1))
                for move in data['moves']:
                    if move['old'] != move['new']:
                        dc.DrawLine(*screen(move['old']), *screen(move['new']))
            diameter = data.get('diameter_mm', 0.5)
            radius = max(5, min(12, round(diameter * scale / 2)))
            for move in data['moves']:
                point = move['new'] if index else move['old']
                px, py = screen(point)
                color = ('#F36C6C' if index and move['uuid'] in issue_ids else
                         '#54D7A2' if index else '#F5B95D')
                dc.SetPen(wx.Pen(color, 2))
                dc.SetBrush(wx.Brush('#263747'))
                dc.DrawCircle(px, py, radius)
                dc.SetPen(wx.Pen('#EAF5FF', 1))
                dc.SetBrush(wx.Brush('#EAF5FF'))
                dc.DrawCircle(px, py, 2)


class ViaArrayPanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        self.preview = None
        self.last_shape = None
        self.filling = False
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(
            self, label='Select existing vias in PCB Editor. TraceForge fits their centers '
                        'inside the selection rectangle; no vias are added.'),
            0, wx.ALL, 9)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        read = wx.Button(self, label='Read & preview selection (F5)')
        read.Bind(wx.EVT_BUTTON, self.on_refresh)
        bar.Add(read, 0, wx.RIGHT, 12)
        bar.Add(wx.StaticText(self, label='Fix'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.axis = wx.Choice(self, choices=['Auto detect', 'Columns', 'Rows'])
        self.axis.SetSelection(0)
        self.axis.Bind(wx.EVT_CHOICE, self.on_axis)
        bar.Add(self.axis, 0, wx.RIGHT, 12)
        bar.Add(wx.StaticText(self, label='Count'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.count = wx.SpinCtrl(self, min=1, max=64, initial=1, size=(78, -1))
        self.count.Disable()
        self.count.Bind(wx.EVT_SPINCTRL, self.invalidate)
        self.count.Bind(wx.EVT_TEXT, self.invalidate)
        bar.Add(self.count, 0, wx.RIGHT, 12)
        calculate = wx.Button(self, label='Preview array')
        calculate.Bind(wx.EVT_BUTTON, self.on_preview)
        bar.Add(calculate, 0, wx.RIGHT, 8)
        self.apply = wx.Button(self, label='Apply to PCB')
        self.apply.Disable()
        self.apply.Bind(wx.EVT_BUTTON, self.on_apply)
        bar.Add(self.apply)
        outer.Add(bar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.summary = wx.StaticText(self, label='Read the selection to see its size and bounds.')
        outer.Add(self.summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.canvas = ViaArrayPreview(self)
        outer.Add(self.canvas, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        for col, title, width in ((0, 'Via', 170), (1, 'Current X', 110),
                                  (2, 'Current Y', 110), (3, 'New X', 110),
                                  (4, 'New Y', 110), (5, 'Move mm', 100)):
            self.table.InsertColumn(col, title, width=width)
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 9)
        self.status = wx.StaticText(
            self, label='Preview checks board bounds, copper clearance and existing track '
                        'attachments. Apply is undoable.')
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 9)
        self.SetSizer(outer)

    def message(self, value, state='pending'):
        self.status.SetLabel(value)
        self.status.SetForegroundColour(self.host.colors.get(state, self.host.colors['pending']))
        self.Layout()

    def invalidate(self, event=None):
        if self.filling:
            return
        if (event and event.GetEventObject() is self.count and
                self.axis.GetSelection() == 0):
            return  # Auto mode ignores the disabled manual count control.
        self.preview = None
        self.apply.Disable()
        self.table.DeleteAllItems()
        self.canvas.show(None)
        if event:
            event.Skip()

    def on_axis(self, event):
        index = self.axis.GetSelection()
        if self.last_shape and index:
            self.count.SetValue(self.last_shape[1] if index == 1 else self.last_shape[0])
        self.count.Enable(index != 0)
        self.invalidate(event)

    def _call(self, operation, done, **payload):
        if self.native is None:
            self.message('Native PCB access is unavailable. Open TraceForge from PCB Editor.',
                         'error')
            return
        self.host.submit_stitching(lambda: self.native(operation, **payload), done, self)

    def on_refresh(self, event=None):
        self.invalidate()

        def done(result):
            self.filling = True
            self.count.SetRange(1, result['count'])
            self.count.SetValue(result['columns'] if self.axis.GetSelection() == 0 else
                                min(self.count.GetValue(), result['count']))
            self.filling = False
            self.last_shape = (result['rows'], result['columns'])
            x0, y0, x1, y1 = result['bounds']
            self.summary.SetLabel(f"{result['count']} selected vias on {result['net']} | "
                                  f'bounds {x0:.3f}, {y0:.3f} to {x1:.3f}, {y1:.3f} mm')
            self.message(f"Detected {result['rows']} rows × {result['columns']} columns. "
                         'Checking placement...', 'ok')
            wx.CallAfter(self.on_preview)

        self._call('via_array_selection', done)

    def on_preview(self, event=None):
        self.invalidate()
        axis = ('auto', 'columns', 'rows')[self.axis.GetSelection()]

        def done(result):
            self.filling = True
            self.count.SetRange(1, result['count'])
            if result['inferred']:
                self.count.SetValue(result['columns'])
            self.filling = False
            self.preview = result
            self.last_shape = (result['rows'], result['columns'])
            self.canvas.show(result)
            for move in result['moves']:
                old, new = move['old'], move['new']
                index = self.table.InsertItem(self.table.GetItemCount(), move['uuid'][:12])
                for col, value in enumerate((old[0], old[1], new[0], new[1],
                                             hypot(new[0] - old[0], new[1] - old[1])), 1):
                    self.table.SetItem(index, col, f'{value:.3f}')
            detected = 'Auto detected' if result['inferred'] else 'Fixed layout'
            self.summary.SetLabel(
                f"{detected}: {result['count']} vias | {result['rows']} rows × "
                f"{result['columns']} columns | "
                f"X {result['pitch_x_mm']:.3f} mm, Y {result['pitch_y_mm']:.3f} mm center spacing")
            if result['issues']:
                reasons = sorted({reason for _identity, reason in result['issues']})
                blocked = len({identity for identity, _reason in result['issues']})
                self.message(
                    f"{result['rows']} x {result['columns']} detected; {blocked} vias cannot "
                    'move safely (red): ' + ', '.join(reasons) +
                    '. Connected tracks or pads may need rerouting first.', 'warning')
            else:
                self.apply.Enable()
                self.message('Array fits the selected rectangle. Click Apply to PCB.', 'ok')

        self._call('via_array_preview', done, fixed_axis=axis,
                   fixed_count=self.count.GetValue())

    def on_apply(self, event=None):
        if not self.preview or not self.preview['accepted']:
            return
        token = self.preview['token']
        self.apply.Disable()

        def done(result):
            self.preview = None
            self.message(result['message'], 'ok')

        self._call('via_array_apply', done, token=token)
