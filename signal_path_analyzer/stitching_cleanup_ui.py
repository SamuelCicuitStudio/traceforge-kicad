"""Inspect and select standalone through vias before manual restitching."""
from __future__ import annotations

import wx


class StitchingCleanupPanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        self.rows = []
        outer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label='Through vias with no direct track, pad, '
                              'other via or copper drawing contact. Zone-only vias '
                              'may be valid stitching; inspect before deleting.')
        outer.Add(intro, 0, wx.ALL, 9)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.unstitched = wx.CheckBox(self, label='Only fewer than two connected copper layers')
        controls.Add(self.unstitched, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        scan = wx.Button(self, label='Scan live PCB (F5)')
        scan.Bind(wx.EVT_BUTTON, self.on_refresh)
        controls.Add(scan, 0, wx.RIGHT, 8)
        select_all = wx.Button(self, label='Select all listed in PCB')
        select_all.Bind(wx.EVT_BUTTON, self.on_select_all)
        controls.Add(select_all, 0, wx.RIGHT, 8)
        outer.Add(controls, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for col, title, width in ((0, 'Net', 180), (1, 'X / Y mm', 190),
                                  (2, 'Drill mm', 90), (3, 'Connected layers', 160),
                                  (4, 'Free / locked', 125)):
            self.table.InsertColumn(col, title, width=width)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_focus)
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 9)
        self.status = wx.StaticText(self, label='Scan first. Click a via to focus it, '
                                   'or select all listed vias for manual deletion in KiCad.')
        outer.Add(self.status, 0, wx.ALL, 9)
        self.SetSizer(outer)

    def message(self, value, state='pending'):
        self.status.SetLabel(value)
        self.status.SetForegroundColour(self.host.colors.get(state,
                                                            self.host.colors['pending']))
        self.Layout()

    def invalidate(self):
        # The shared busy overlay handles the operation lifecycle. Keep scan rows
        # visible after a transient KiCad error so the user can retry selection.
        pass

    def call(self, operation, done, **payload):
        if not self.native:
            self.message('Open TraceForge from PCB Editor for native access.', 'error')
            return
        self.host.submit_stitching(lambda: self.native(operation, **payload), done, self)

    def on_refresh(self, event=None):
        self.table.DeleteAllItems()
        self.rows = []
        self.message('Scanning live through vias...')

        def done(result):
            self.rows = result['vias']
            for row in self.rows:
                index = self.table.InsertItem(self.table.GetItemCount(), row['net'])
                values = (f"{row['x_mm']:.3f} / {row['y_mm']:.3f}",
                          f"{row['drill_mm']:.3f}",
                          f"{len(row['connected_layers'])}: " +
                          ', '.join(row['connected_layers']),
                          ('free' if row['free'] else 'ordinary') +
                          (' / locked' if row['locked'] else ''))
                for col, value in enumerate(values, 1):
                    self.table.SetItem(index, col, value)
            self.message(f"Found {result['count']} standalone through vias. "
                         'Select all only if you intend to remove and redo them. '
                         'No vias were changed.', 'warning' if result['count'] else 'ok')

        self.call('stitch_loose_scan', done,
                  unstitched_only=self.unstitched.GetValue())

    def on_focus(self, event):
        index = event.GetIndex()
        if index < len(self.rows):
            self.call('via_manage_focus',
                      lambda result: self.message('Via selected and zoomed in KiCad.', 'ok'),
                      ids=[self.rows[index]['uuid']], fast=True)

    def on_select_all(self, event):
        ids = [row['uuid'] for row in self.rows if not row['locked']]
        if not ids:
            self.message('No unlocked vias are listed. Scan first.', 'warning')
            return
        self.call('via_manage_focus',
                  lambda result: self.message(
                      f"Selected {result['count']} vias in PCB Editor. Delete there if "
                      'intended; refill zones with B when ready.', 'ok'),
                  ids=ids, fast=True)
