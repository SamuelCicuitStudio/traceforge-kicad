"""Compact tool selector with persistent child controls, no nested tab row."""

from __future__ import annotations

import wx


class ToolWorkspace(wx.Panel):
    def __init__(self, parent, host, names):
        super().__init__(parent)
        self.host = host
        if host.dark:
            self.SetBackgroundColour("#222C3A")
            self.SetForegroundColour("#E5EDF8")
        self.selector = wx.Choice(self, choices=names)
        self.selector.SetSelection(0)
        self.book = wx.Simplebook(self)
        box = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        bar.Add(wx.StaticText(self, label="Tool:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        bar.Add(self.selector, 1)
        box.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
        box.Add(self.book, 1, wx.EXPAND)
        self.SetSizer(box)
        self.selector.Bind(wx.EVT_CHOICE, lambda event: self.select(self.selector.GetSelection()))

    def add(self, page, name):
        page.Reparent(self.book)
        self.book.AddPage(page, name)

    def select(self, index):
        self.selector.SetSelection(index)
        self.book.SetSelection(index)
        self.host.workspace_changed()

    @property
    def active_index(self):
        return self.selector.GetSelection()


def utility_window(host, title):
    frame = wx.Frame(host, title=title, size=(880, 620), style=wx.DEFAULT_FRAME_STYLE)
    frame.Bind(wx.EVT_CLOSE, lambda event: frame.Hide())
    return frame
