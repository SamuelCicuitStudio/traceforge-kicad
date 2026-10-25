"""Manual selected-via/pad workflow; no selection polling or automatic board edits."""
import wx


class EndpointDialog(wx.Dialog):
    def __init__(self, host, service):
        super().__init__(host, title='Detect between selected PCB items', size=(760, 620),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.host, self.service, self.result, self.endpoints = host, service, None, None
        box = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label='Select two pads, vias, tracks/arcs or components.\n'
                              'Detect follows connected tracks and allowed series parts, then '
                              'highlights and fits the path.')
        box.Add(intro, 0, wx.ALL, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label='Resistors up to (ohms):'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.ohms = wx.SpinCtrlDouble(self, min=0, max=1000000, initial=100, inc=10)
        row.Add(self.ohms, 0, wx.LEFT | wx.RIGHT, 8)
        self.caps = wx.CheckBox(self, label='Cross series capacitors')
        self.caps.SetValue(True)
        self.pair = wx.CheckBox(self, label='Include differential partner')
        self.pair.SetValue(True)
        row.Add(self.caps, 0, wx.RIGHT, 8)
        row.Add(self.pair)
        box.Add(row, 0, wx.ALL, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Detect / update path', self.detect),
                               ('Use new PCB endpoints', self.new_endpoints)]:
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.RIGHT, 8)
        box.Add(row, 0, wx.LEFT | wx.RIGHT, 10)
        self.details = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        box.Add(self.details, 1, wx.EXPAND | wx.ALL, 10)
        grid = wx.FlexGridSizer(2, 2, 6, 8)
        grid.AddGrowableCol(1)
        self.group, self.name = wx.TextCtrl(self, value='Selected paths'), wx.TextCtrl(self)
        for label, control in [('Group', self.group), ('Chain name', self.name)]:
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        box.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        note = wx.StaticText(self, label='Saved chains describe whole nets, including branches; '
                             'the preview shows only the routed endpoint path.\n'
                             'Endpoint order is not driver direction. '
                             'No timing limits are guessed.')
        box.Add(note, 0, wx.ALL, 10)
        if service.session.config and service.session.config.auto:
            box.Add(wx.StaticText(self, label='Adding also saves the current auto-detected chain '
                                  'definitions. Review their timing in Chain editor.'),
                    0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.status = wx.StaticText(self, label='Select endpoints, then click Detect.')
        box.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.add = wx.Button(self, label='Add reviewed chain(s)')
        self.add.Disable()
        self.add.Bind(wx.EVT_BUTTON, self.save)
        row.Add(self.add, 0, wx.RIGHT, 8)
        close = wx.Button(self, wx.ID_CLOSE)
        close.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        row.Add(close)
        box.Add(row, 0, wx.ALL, 10)
        self.SetSizer(box)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        for control in (self.ohms, self.caps, self.pair):
            control.Bind(wx.EVT_CHECKBOX if isinstance(control, wx.CheckBox) else
                         wx.EVT_SPINCTRLDOUBLE, self.changed)
        self.ohms.Bind(wx.EVT_TEXT, self.changed)

    def changed(self, event):
        self.invalidate()
        event.Skip()

    def invalidate(self):
        self.result = None
        self.add.Disable()

    def message(self, text, state='pending'):
        self.status.SetLabel(text)
        self.status.SetForegroundColour(self.host.colors[state])
        self.Layout()

    def on_close(self, event):
        if self.host.actions_pending:
            event.Veto()
        else:
            self.EndModal(wx.ID_CLOSE)

    def new_endpoints(self, event):
        self.endpoints = None
        self.detect()

    def detect(self, event=None):
        payload = dict(max_ohms=self.ohms.GetValue(), capacitors=self.caps.GetValue(),
                       include_pair=self.pair.GetValue(), endpoints=self.endpoints)
        self.invalidate()
        self.host.submit_stitching(lambda: self.service.detect(**payload), self.accept, self)

    def accept(self, result):
        if 'choices' in result:
            choices = result['choices']
            with wx.SingleChoiceDialog(self, 'Choose the signal to trace (first 128 shown).',
                                       'Choose endpoint path',
                                       [c['label'] for c in choices]) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    self.message('Path choice cancelled; no chains added.')
                    return
                self.endpoints = choices[dialog.GetSelection()]['endpoints']
            self.detect()
            return
        self.result = result
        self.endpoints = [e['id'] for e in result['primary']['endpoints']]
        lines = []
        paths = [p for p in (result['primary'], result['partner']) if p]
        for path, existing in zip(paths, self.service.statuses(result)):
            lines += [f"{path['endpoints'][0]['label']} -> {path['endpoints'][1]['label']}",
                      'Nets: ' + ' -> '.join(path['nets'])]
            lines += [f"  {p['reference']}: {p['value']} ({p['type']})" for p in path['components']]
            lines += [f"Routed track objects: {path['track_mm']:.3f} mm "
                      '(excludes via barrels and part internals).']
            if path['branches']:
                lines += ['Branch/overlap detected: one shortest routed-item path is shown.']
            lines += [f'Already included: {existing.group}/{existing.name}' if existing else
                      'New chain; not yet added.', '']
        if result['pair_note']:
            lines += [result['pair_note']]
        self.details.ChangeValue('\n'.join(lines))
        if not self.name.GetValue():
            self.name.ChangeValue(result['primary']['nets'][0].rsplit('/', 1)[-1])
        self.add.Enable(not all(self.service.statuses(result)))
        self.message('Path highlighted and fitted in PCB Editor. Review before adding.', 'routed')

    def save(self, event):
        if self.result:
            result, group, name = self.result, self.group.GetValue(), self.name.GetValue()
            def done(message):
                self.accept(result)
                self.message(message, 'ok')
            self.host.submit_stitching(lambda: self.service.add(result, group, name), done, self)
