"""One Via Tools tab with a compact selector for the three via workflows."""
from __future__ import annotations

import wx

from .stitching_ui import StitchingPanel
from .trace_fence_ui import TraceFencePanel
from .via_array_ui import ViaArrayPanel


class ViaToolsPanel(wx.Panel):
    names = ('Via Stitching', 'Via Fencing', 'Via Array')

    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host = host
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        outer = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        bar.AddStretchSpacer()
        bar.Add(wx.StaticText(self, label='Via tool:'), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.selector = wx.Choice(self, choices=list(self.names), size=(160, -1))
        self.selector.SetSelection(0)
        self.selector.SetToolTip('Switch between Via Stitching, Via Fencing, and Via Array.')
        self.selector.Bind(wx.EVT_CHOICE, self.on_choice)
        bar.Add(self.selector)
        outer.Add(bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 6)

        self.book = wx.Simplebook(self)
        self.stitching = StitchingPanel(self.book, host, native)
        self.fencing = TraceFencePanel(self.book, host, native)
        self.array = ViaArrayPanel(self.book, host, native)
        for page, name in zip((self.stitching, self.fencing, self.array), self.names):
            self.book.AddPage(page, name)
        outer.Add(self.book, 1, wx.EXPAND)
        self.SetSizer(outer)

    @property
    def active_index(self):
        return self.selector.GetSelection()

    @property
    def active_page(self):
        return (self.stitching, self.fencing, self.array)[self.active_index]

    def on_choice(self, event):
        self.book.SetSelection(self.active_index)
        self.host.schedule_auto_refresh()
