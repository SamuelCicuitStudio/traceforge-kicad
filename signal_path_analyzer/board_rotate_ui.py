"""Exact-angle rotation for selected items in the open PCB Editor."""
from __future__ import annotations

import wx


class BoardRotatePanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label='Rotate selected PCB components by an exact angle.'),
                  0, wx.ALL, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label='Rotation (degrees)'), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.angle = wx.TextCtrl(self, value='45', size=(90, -1))
        row.Add(self.angle, 0, wx.RIGHT, 8)
        button = wx.Button(self, label='Rotate selected items')
        button.Enable(native is not None)
        button.Bind(wx.EVT_BUTTON, self.on_apply)
        row.Add(button)
        outer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(wx.StaticText(self, label='Positive angles rotate counterclockwise; '
                                'negative angles rotate clockwise. Each component rotates '
                                'around its anchor. KiCad Undo restores the rotation.'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(wx.StaticText(self, label='For shapes or zones, set KiCad\'s rotation step '
                                'in Preferences > PCB Editor > Editing Options, then use R.'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(wx.StaticText(self, label='After rotating connected components, inspect '
                                'their traces and run DRC. Zone fills are updated automatically.'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.status = wx.StaticText(self, label='Select items in the PCB Editor, then rotate.')
        outer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)

    def message(self, text, state='pending'):
        self.status.SetForegroundColour(self.host.colors[state])
        self.status.SetLabel(text)
        self.Layout()

    def invalidate(self):
        pass

    def on_apply(self, _event=None):
        angle = self.angle.GetValue().strip()

        def done(result):
            self.host.refresh_policy.invalidate()
            parts = [f"{count} {name}" for name, count in
                     (("component(s)", result['components']),
                      ("shape(s)", result['shapes']),
                      ("zone(s)", result['zones'])) if count]
            self.message(f"Rotated {', '.join(parts)} by {result['angle']:g}°. "
                         'Save the PCB and run DRC.', 'ok')

        self.host.submit_stitching(
            lambda: self.native('rotate_apply', angle=angle), done, self)

    def on_refresh(self, _event=None):
        self.message('Select items in the PCB Editor, then rotate.')
