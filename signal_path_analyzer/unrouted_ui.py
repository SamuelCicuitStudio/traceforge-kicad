"""Navigate live unrouted gaps without a DRC run."""
import wx


class UnroutedPanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        self.rows = []
        self.visible_rows = []
        self.loaded = False
        self.loading = False
        self.summary = {}
        root = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        for title, handler in [('Refresh gaps', self.on_refresh),
                               ('Previous', lambda e: self.step(-1)),
                               ('Next', lambda e: self.step(1)),
                               ('Highlight + zoom', self.on_focus),
                               ('Clear highlight', self.on_clear)]:
            button = wx.Button(self, label=title)
            button.Bind(wx.EVT_BUTTON, handler)
            button.Enable(native is not None)
            bar.Add(button, 0, wx.RIGHT, 6)
        root.Add(bar, 0, wx.ALL, 8)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        filters.Add(wx.StaticText(self, label='Filter net / reference / class:'), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.filter = wx.SearchCtrl(self, size=(300, -1))
        self.filter.Bind(wx.EVT_TEXT, lambda e: self.fill())
        filters.Add(self.filter, 0, wx.RIGHT, 12)
        self.whole_net = wx.CheckBox(self, label='Highlight whole net')
        self.whole_net.SetValue(False)
        filters.Add(self.whole_net, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(filters, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (title, width) in enumerate([
                ('Net', 260), ('State', 130), ('From', 130), ('To', 130),
                ('Gap mm', 90), ('From X/Y mm', 150), ('To X/Y mm', 150), ('Netclass', 130)]):
            self.table.InsertColumn(index, title, width=width)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_focus)
        self.table.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_focus)
        root.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.status = wx.StaticText(self, label='Refresh to locate the remaining copper gaps.')
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        note = wx.StaticText(self, label='Click a row to highlight its endpoints '
                             'and zoom to the gap. '
                             'Shortest gaps come first. Refresh after routing. '
                             'No DRC or zone refill. '
                             'Nearest-anchor links can differ from KiCad drawn ratsnest tree.')
        note.Wrap(1060)
        root.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(root)

    def invalidate(self):
        self.loaded = False

    def message(self, text, state='pending'):
        self.status.SetLabel(text)
        self.status.SetForegroundColour(self.host.colors.get(state, self.host.colors['pending']))
        self.Layout()

    def _call(self, operation, done, **payload):
        if self.native is None:
            self.message('Open this tool through the PCB Editor native bridge.', 'error')
            return
        self.host.submit_stitching(lambda: self.native(operation, **payload), done, self)

    def on_refresh(self, _event=None):
        def done(result):
            self.rows = result['rows']
            self.summary = result
            self.loaded = True
            self.fill()
        self._call('unrouted_scan', done)

    def fill(self):
        selected = self.table.GetFirstSelected()
        selected_id = (self.visible_rows[selected]['id'] if selected >= 0 else None)
        text = self.filter.GetValue().casefold().strip()
        self.visible_rows = [r for r in self.rows if not text or text in
                             (' '.join([r['net'], r['netclass'], r['a']['label'],
                                        r['b']['label']])).casefold()]
        self.loading = True
        self.table.Freeze()
        try:
            self.table.DeleteAllItems()
            for row in self.visible_rows:
                index = self.table.InsertItem(self.table.GetItemCount(), row['net'])
                cells = [row['status'], row['a']['label'], row['b']['label'],
                         f"{row['gap_mm']:.4f}",
                         ' / '.join(f'{n:.3f}' for n in row['a']['position']),
                         ' / '.join(f'{n:.3f}' for n in row['b']['position']), row['netclass']]
                for col, value in enumerate(cells, 1):
                    self.table.SetItem(index, col, value)
                if row['id'] == selected_id:
                    self.table.Select(index)
        finally:
            self.table.Thaw()
            self.loading = False
        native = self.summary.get('native_airwires', '?')
        self.message(f'{len(self.visible_rows)} shown / {len(self.rows)} gaps in '
                     f"{self.summary.get('nets', 0)} nets. KiCad native airwires: {native}. "
                     'Current filled copper; no refill performed.')

    def on_focus(self, _event=None):
        if self.loading:
            return
        selected = self.table.GetFirstSelected()
        if selected < 0 or selected >= len(self.visible_rows):
            self.message('Click a connection row, or use Next to focus the first gap.')
            return
        row = self.visible_rows[selected]
        def done(result):
            if result.get('resolved'):
                self.message(result.get('message', 'Connection changed; refreshing.'))
                self.on_refresh()
            else:
                self.message(f"{row['net']}: {row['a']['label']} to {row['b']['label']}; "
                             f"gap {row['gap_mm']:.4f} mm. "
                             + ('Zoomed to gap.' if result.get('zoomed') else
                                'Endpoints highlighted; zoom unavailable in this editor window.'))
        self._call('unrouted_focus', done, id=row['id'], whole_net=self.whole_net.GetValue())

    def step(self, direction):
        if not self.visible_rows:
            self.message('No gaps in the current filter. Refresh after board changes.')
            return
        selected = self.table.GetFirstSelected()
        index = ((selected+direction) % len(self.visible_rows) if selected >= 0 else
                 0 if direction > 0 else len(self.visible_rows)-1)
        if selected == index:
            self.on_focus()
            return
        if selected >= 0:
            self.table.Select(selected, False)
        self.table.Select(index)
        self.table.EnsureVisible(index)

    def on_clear(self, _event=None):
        self._call('unrouted_clear', lambda result: self.message('Highlight cleared.'))
