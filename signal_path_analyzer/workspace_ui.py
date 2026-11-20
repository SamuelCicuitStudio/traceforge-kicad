"""Compact tool selector with persistent child controls, no nested tab row."""

from __future__ import annotations

import wx


class ToolWorkspace(wx.Panel):
    def __init__(self, parent, host, names):
        super().__init__(parent)
        self.host = host
        if host.dark:
            self.SetBackgroundColour("#303030")
            self.SetForegroundColour("#ededed")
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
    frame = wx.Frame(
        host, title=title, size=(880, 620), style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT
    )
    frame.Bind(wx.EVT_CLOSE, lambda event: frame.Hide())
    return frame


def sync_overlay_order(host, want):
    """Keep auxiliary windows above the overlay, without floating over other apps."""
    owned = []
    for window in wx.GetTopLevelWindows():
        parent = window.GetParent()
        while parent:
            if parent is host:
                owned.append(window)
                break
            parent = parent.GetParent()
    shown = [window for window in owned if window.IsShown()]
    state = (bool(want), tuple(window.GetHandle() for window in shown))
    if getattr(host, '_overlay_order_state', None) == state:
        return

    def topmost(window, enabled):
        style = window.GetWindowStyle()
        if bool(style & wx.STAY_ON_TOP) != bool(enabled):
            window.SetWindowStyle(style | wx.STAY_ON_TOP if enabled else style & ~wx.STAY_ON_TOP)

    # A topmost owner can cover its ordinary modeless child when Windows
    # reapplies the overlay style. Give shown children the foreground band and
    # let their owner stay normal until they close or hide.
    # Demoting an owned Win32 window can also demote its owner. Clear the
    # whole family before promoting the desired windows, only when that
    # family/focus state changes (never raise it on every timer tick).
    for window in owned:
        topmost(window, False)
    topmost(host, False)
    host.on_top = bool(want and not shown)
    if host.on_top:
        topmost(host, True)
    elif want:
        for window in shown:
            topmost(window, True)
    host._overlay_order_state = state


def show_utility(host, window):
    window.Show()
    window.Iconize(False)
    host.on_overlay(None)
    window.Raise()
