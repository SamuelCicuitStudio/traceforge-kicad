"""Preview-first redundant track cleanup controls."""
import wx


class TraceCleanupPanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native, self.preview = host, native, None
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        box = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='Remove duplicate / fully covered copper without changing '
                             'the copper shape. Dangling endpoints use KiCad connectivity checks.\n'
                             'Dangling tracks start unchecked: they may be intentional '
                             'or unfinished. '
                             'Vias, locked and grouped items are preserved.')
        box.Add(note, 0, wx.ALL, 10)
        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(wx.StaticText(self, label='Exact net name (blank = whole board)'), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.net = wx.TextCtrl(self)
        self.net.Bind(wx.EVT_TEXT, lambda event: self.invalidate())
        top.Add(self.net, 1, wx.RIGHT, 8)
        scan = wx.Button(self, label='Scan / Preview (F5)')
        scan.Bind(wx.EVT_BUTTON, self.on_refresh)
        top.Add(scan)
        box.Add(top, 0, wx.EXPAND | wx.ALL, 10)
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_row.Add(wx.StaticText(self, label='Show layer'), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.layer = wx.Choice(self, choices=['All copper layers'])
        self.layer.SetSelection(0)
        self.layer.Bind(wx.EVT_CHOICE, self.on_layer)
        filter_row.Add(self.layer, 0, wx.RIGHT, 10)
        self.layer_summary = wx.StaticText(self, label='Scan to see counts by copper layer.')
        filter_row.Add(self.layer_summary, 1, wx.ALIGN_CENTER_VERTICAL)
        box.Add(filter_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.table.SetBackgroundColour('#19212D' if host.dark else '#FFFFFF')
        self.table.SetForegroundColour('#E5EDF8' if host.dark else '#18212E')
        self.table.EnableCheckBoxes()
        for i, (label, width) in enumerate([('Remove', 70), ('Net', 240), ('Layer', 85),
                                            ('Track length (mm)', 145), ('Finding', 280)]):
            self.table.InsertColumn(i, label, width=width)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        box.Add(self.table, 1, wx.EXPAND | wx.ALL, 10)
        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.remove = wx.Button(self, label='Apply checked cleanup')
        self.remove.Bind(wx.EVT_BUTTON, self.on_remove)
        self.remove.Disable()
        bottom.Add(self.remove, 0, wx.RIGHT, 10)
        recheck = wx.Button(self, label='Recheck length matching')
        recheck.Bind(wx.EVT_BUTTON, self.on_recheck)
        bottom.Add(recheck, 0, wx.RIGHT, 10)
        self.status = wx.StaticText(self, label='Scan to preview. '
                                    'No tracks are removed automatically.')
        bottom.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL)
        box.Add(bottom, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(box)
        self.Enable(native is not None)

    def invalidate(self):
        self.preview = None
        self.remove.Disable()
        self.table.DeleteAllItems()

    def message(self, text, state='routed'):
        self.status.SetForegroundColour(self.host.colors[state])
        self.status.SetLabel(text)
        self.Layout()

    def on_recheck(self, event):
        self.host.notebook.SetSelection(0)
        self.host.on_refresh()

    def on_refresh(self, event=None):
        net = self.net.GetValue().strip()
        def done(result):
            self.invalidate()
            self.preview = result
            old_layer = self.layer.GetStringSelection()
            choices = ['All copper layers', *result['layers']]
            self.layer.SetItems(choices)
            self.layer.SetStringSelection(old_layer if old_layer in choices else choices[0])
            self.fill_rows()
            counts = {layer: sum(row['layer'] == layer for row in
                                result['redundant'] + result['fusions'] + result['dangling'])
                      for layer in result['layers']}
            self.layer_summary.SetLabel(' | '.join(f'{layer}: {count}'
                                                    for layer, count in counts.items()))
            self.message(f"{len(result['redundant'])} redundant tracks; "
                         f"{result['removed_length_mm']:.6f} mm extra counted length. "
                         f"{len(result['fusions'])} overlap groups to fuse; "
                         f"{len(result['dangling'])} dangling tracks (unchecked); "
                         f"{len(result['partial'])} retained overlaps.", 'ok')
        self.host.submit_stitching(lambda: self.native('cleanup_scan', net=net), done, self)

    def on_layer(self, event):
        self.fill_rows()

    def fill_rows(self):
        self.table.DeleteAllItems()
        self.visible_rows = []
        if self.preview is None:
            return
        layer = self.layer.GetStringSelection()
        rows = (self.preview['redundant'] + self.preview['fusions'] +
                self.preview['dangling'])
        for row in rows:
            if layer != 'All copper layers' and row['layer'] != layer:
                continue
            index = self.table.InsertItem(self.table.GetItemCount(), '')
            for column, value in enumerate([row['net'], row['layer'],
                                            f"{row['length_mm']:.6f}", row['reason']], 1):
                self.table.SetItem(index, column, value)
            state = 'warning' if row in self.preview['dangling'] else 'ok'
            self.table.SetItemTextColour(index, self.host.colors[state])
            self.table.CheckItem(index, row not in self.preview['dangling'])
            self.visible_rows.append(row)
        self.remove.Enable(bool(self.visible_rows))

    def on_select(self, event):
        if not self.preview:
            return
        row = self.visible_rows[event.GetIndex()]
        token = self.preview['token']
        self.host.submit_stitching(lambda: self.native('cleanup_highlight', token=token,
                                                      ids=[row['id']]),
                                   lambda result: self.message('Preview track highlighted '
                                                               'in KiCad.'), self)

    def on_remove(self, event):
        if not self.preview:
            return
        ids = [row['id'] for i, row in enumerate(self.visible_rows)
               if self.table.IsItemChecked(i)]
        if not ids:
            self.message('Check the tracks to remove.', 'warning')
            return
        dangling = sum(row['id'] in ids for row in self.preview['dangling'])
        if dangling and wx.MessageBox(
                f'Remove {dangling} reviewed dangling tracks?\n'
                'This can remove intentional stubs or unfinished routing.\n'
                'Undo will be available in KiCad.', 'Remove reviewed dangling tracks',
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent=self) != wx.YES:
            return
        token = self.preview['token']
        def done(result):
            self.invalidate()
            self.host.refresh_policy.invalidate()
            self.message(f"Removed {result['removed']} checked tracks; "
                         f"fused {result['fused']} overlap groups. "
                         'KiCad Undo is available. Refresh Signals to update lengths.', 'ok')
        self.host.submit_stitching(lambda: self.native('cleanup_remove', token=token, ids=ids),
                                   done, self)
