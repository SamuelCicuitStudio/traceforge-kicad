"""Read-only live via-in-SMT-pad inventory with native PCB focus."""
from __future__ import annotations

import wx

CONTACT_TYPES = {
    'full': ('Full via in pad', wx.Colour(45, 155, 75)),
    'hole': ('Partial: hole touches pad', wx.Colour(210, 70, 70)),
    'partial': ('Partial: annulus only', wx.Colour(215, 145, 35)),
}


class ViaPadPanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        outer = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        bar.Add(wx.StaticText(self, label='Via hole or annulus touching SMT pads (all nets)'),
                0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        refresh = wx.Button(self, label='Scan live PCB (F5)')
        refresh.Bind(wx.EVT_BUTTON, self.on_refresh)
        bar.Add(refresh)
        self.loader = wx.ActivityIndicator(self)
        bar.Add(self.loader, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        self.loader.Hide()
        outer.Add(bar, 0, wx.ALL, 9)
        legend = wx.BoxSizer(wx.HORIZONTAL)
        for title, colour in CONTACT_TYPES.values():
            label = wx.StaticText(self, label=title)
            label.SetForegroundColour(colour)
            legend.Add(label, 0, wx.RIGHT, 20)
        outer.Add(legend, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.table = wx.TreeCtrl(self, style=wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS |
                                wx.TR_LINES_AT_ROOT | wx.TR_SINGLE)
        self.root = self.table.AddRoot('Via-in-pad results')
        self.table.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_focus)
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 9)
        self.status = wx.StaticText(self, label='Scan the open board, then click a row to '
                                   'select and zoom to that via in PCB Editor.')
        outer.Add(self.status, 0, wx.ALL, 9)
        self.SetSizer(outer)

    def message(self, value, state='pending'):
        self.status.SetLabel(value)
        self.status.SetForegroundColour(self.host.colors.get(state,
                                                            self.host.colors['pending']))
        self.Layout()

    def call(self, operation, done, **payload):
        if not self.native:
            self.message('Open TraceForge from PCB Editor for native access.', 'error')
            return
        if self.host.busy or self.host.actions_pending or self.host.closing:
            self.message('Another KiCad operation is still running.', 'warning')
            return
        self.loader.Show()
        self.loader.Start()
        self.Layout()

        def finished(result):
            self.invalidate()
            done(result)

        self.host.submit_stitching(lambda: self.native(operation, **payload),
                                   finished, self)

    def invalidate(self):
        self.loader.Stop()
        self.loader.Hide()
        self.Layout()

    def on_refresh(self, event=None):
        self.table.DeleteAllItems()
        self.root = self.table.AddRoot('Via-in-pad results')
        self.message('Scanning live PCB...')

        def done(result):
            groups = {}
            for via in result['vias']:
                for pad in via['pads']:
                    groups.setdefault(pad['reference'], []).append((via, pad))
            for reference, entries in sorted(groups.items()):
                ids = list(dict.fromkeys(via['uuid'] for via, _ in entries))
                component = self.table.AppendItem(self.root,
                                                   f'{reference} - {len(ids)} vias')
                self.table.SetItemData(component, ids)
                for contact, (title, colour) in CONTACT_TYPES.items():
                    matching = [(via, pad) for via, pad in entries
                                if pad['contact'] == contact]
                    if not matching:
                        continue
                    section = self.table.AppendItem(component,
                                                    f'{title} - {len(matching)} contacts')
                    self.table.SetItemTextColour(section, colour)
                    self.table.SetItemData(section,
                                           list(dict.fromkeys(via['uuid'] for via, _ in matching)))
                    for via, pad in sorted(matching, key=lambda pair: (
                            pair[1]['pad'], pair[0]['x_mm'], pair[0]['y_mm'])):
                        label = (f"Pad {pad['pad']} | "
                                 f"via: {via['net']} / pad: {pad['pad_net']} | "
                                 f"X {via['x_mm']:.3f}, Y {via['y_mm']:.3f} mm | "
                                 f"drill {via['drill_mm']:.3f} mm | "
                                 f"{', '.join(pad['layers'])}")
                        child = self.table.AppendItem(section, label)
                        self.table.SetItemTextColour(child, colour)
                        self.table.SetItemData(child, [via['uuid']])
                self.table.Expand(component)
            self.table.ExpandAll()
            self.message(f"{result['count']} vias touching pads in {len(groups)} components. "
                         'Colored rows show full, hole-overlap and annulus-only contact. '
                         'Click a via to highlight and zoom to it. '
                         'Scan is read-only.', 'warning' if result['count'] else 'ok')

        self.call('via_manage_pad_scan', done)

    def on_focus(self, event):
        ids = self.table.GetItemData(event.GetItem())
        if ids:
            self.message('Selecting and zooming in PCB Editor...')
            self.call('via_manage_focus',
                      lambda result: self.message(
                          f"Focused {result['count']} via(s) in PCB Editor.", 'ok'),
                      ids=ids, fast=True)
