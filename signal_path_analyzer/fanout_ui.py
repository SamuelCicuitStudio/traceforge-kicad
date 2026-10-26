"""Selected-footprint BGA breakout controls and read-only preview."""
from __future__ import annotations

import wx

from .fanout import fit_guidance, validate


class FanoutPreview(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self.data, self.preview = None, None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((300, 240))
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        host = self.GetParent().host
        dc.SetBackground(wx.Brush('#19212D' if host.dark else '#FFFFFF'))
        dc.Clear()
        if not self.data:
            dc.SetTextForeground(host.colors['pending'])
            dc.DrawText('Select a BGA in KiCad, then Analyze selection.', 12, 12)
            return
        pads = self.data['pads']
        rows = ((self.preview or {}).get('accepted', []) +
                (self.preview or {}).get('breakout_only', []))
        points = ([p['position'] for p in pads] + [p['end'] for p in rows] +
                  [point for row in rows for point in row.get('route', [])])
        xs, ys = zip(*points)
        left, top = min(xs) - 1, min(ys) - 1
        scale = min(max(self.GetClientSize().width - 24, 1) / (max(xs) - left + 1),
                    max(self.GetClientSize().height - 24, 1) / (max(ys) - top + 1))

        def pixel(point):
            return wx.Point(round(12 + (point[0] - left) * scale),
                            round(12 + (point[1] - top) * scale))

        rejected = {r['pad'] for r in (self.preview or {}).get('rejected', [])}
        for pad in pads:
            state = 'warning' if pad['number'] in rejected else 'pending'
            dc.SetPen(wx.Pen(host.colors[state]))
            dc.SetBrush(wx.Brush(host.colors[state]))
            dc.DrawCircle(pixel(pad['position']), max(2, round(min(pad['size']) * scale / 2)))
            if len(pads) < 150:
                dc.SetTextForeground(host.colors[state])
                p = pixel(pad['position'])
                dc.DrawText(pad['number'], p.x + 3, p.y + 3)
        for row in rows:
            color = host.colors['warning'] if 'reason' in row else host.colors['ok']
            dc.SetPen(wx.Pen(color, max(1, round(row['width'] * scale))))
            dc.DrawLine(pixel(row['start']), pixel(row['end']))
            dc.SetPen(wx.Pen(host.colors['routed'], max(1, round(row['width'] * scale))))
            for a, b in zip(row.get('route', []), row.get('route', [])[1:]):
                dc.DrawLine(pixel(a), pixel(b))
            dc.SetPen(wx.Pen(color, 1))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawCircle(pixel(row['end']), max(2, round(row['diameter'] * scale / 2)))


class FanoutPanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native, self.data, self.preview = host, native, None, None
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        outer = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        button = wx.Button(self, label='Analyze PCB selection (F5)')
        button.Bind(wx.EVT_BUTTON, self.on_refresh)
        top.Add(button, 0, wx.RIGHT, 10)
        self.summary = wx.StaticText(self, label='Select one BGA footprint '
                                     'or its pads in PCB Editor.')
        top.Add(self.summary, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(top, 0, wx.EXPAND | wx.ALL, 8)
        self.fit = wx.StaticText(self, label='Fit guidance appears after Analyze selection.')
        outer.Add(self.fit, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        body = wx.BoxSizer(wx.HORIZONTAL)
        form = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        self.mode = wx.Choice(self, choices=['Dogbone via in adjacent gap',
                                             'Via-in-pad', 'Auto escape to BGA edge'])
        self.mode.SetSelection(0)
        self.source = wx.Choice(self, choices=['Active board preset', 'Netclass per net', 'Custom'])
        self.source.SetSelection(0)
        self.escape_layer = wx.Choice(self, choices=['B.Cu'])
        self.escape_layer.SetSelection(0)
        self.escape_layer.Disable()
        for label, control in (('Method', self.mode), ('Via size source', self.source),
                               ('Auto escape layer', self.escape_layer)):
            form.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        self.fields = {}
        for key, label, value in (('diameter', 'Via diameter (mm)', '.6'),
                                  ('drill', 'Drill diameter (mm)', '.25'),
                                  ('width', 'Track width (mm)', '.15'),
                                  ('clearance', 'Minimum clearance (mm)', '.15'),
                                  ('offset_x', 'Dogbone X offset; 0 = local auto', '0'),
                                  ('offset_y', 'Dogbone Y offset; 0 = local auto', '0'),
                                  ('edge', 'Board edge setback (mm)', '.5'),
                                  ('include', 'Include nets; comma-separated globs', '*'),
                                  ('exclude', 'Exclude nets; comma-separated globs', ''),
                                  ('pads', 'Pad numbers; comma-separated globs', '*')):
            control = wx.TextCtrl(self, value=value)
            self.fields[key] = control
            form.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
            control.Bind(wx.EVT_TEXT, self.settings_changed)
        form.AddGrowableCol(1)
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(form, 0, wx.EXPAND)
        self.netclass_width = wx.CheckBox(self, label='Respect netclass track widths')
        self.netclass_width.SetValue(True)
        self.allow_via_in_pad = wx.CheckBox(self, label='Fabrication supports via-in-pad')
        left.Add(self.netclass_width, 0, wx.TOP, 8)
        left.Add(self.allow_via_in_pad, 0, wx.TOP, 8)
        body.Add(left, 0, wx.ALL, 8)
        self.canvas = FanoutPreview(self)
        body.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 8)
        outer.Add(body, 1, wx.EXPAND)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (('Suggest settings', self.on_suggest),
                                ('Preview fanout', self.on_preview),
                                ('Clear preview', self.clear_preview)):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            bar.Add(button, 0, wx.RIGHT, 5)
        self.apply = wx.Button(self, label='Apply accepted breakouts')
        self.apply.Enable(False)
        self.apply.Bind(wx.EVT_BUTTON, self.on_apply)
        bar.Add(self.apply)
        self.remove = wx.Button(self, label='Remove generated fanout')
        self.remove.Enable(False)
        self.remove.Bind(wx.EVT_BUTTON, self.on_remove)
        bar.Add(self.remove, 0, wx.LEFT, 5)
        outer.Add(bar, 0, wx.ALL, 8)
        self.rows = wx.ListCtrl(self, style=wx.LC_REPORT, size=(-1, 140))
        for i, (label, width) in enumerate((('Pad', 70), ('Net', 220),
                                           ('Status / reason', 340), ('Via / drill mm', 140))):
            self.rows.InsertColumn(i, label, width=width)
        outer.Add(self.rows, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.status = wx.StaticText(self, label='Dogbone/via-in-pad breakouts or bounded '
                                    'single-ended escape to the BGA edge. No pair matching.')
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)
        for control in (self.mode, self.source):
            control.Bind(wx.EVT_CHOICE, self.changed)
        self.escape_layer.Bind(wx.EVT_CHOICE, self.settings_changed)
        for control in (self.netclass_width, self.allow_via_in_pad):
            control.Bind(wx.EVT_CHECKBOX, self.settings_changed)
        if host.dark:
            self.rows.SetBackgroundColour('#19212D')
            self.rows.SetForegroundColour('#E5EDF8')
            for child in self.GetChildren():
                if isinstance(child, (wx.StaticText, wx.CheckBox)):
                    child.SetForegroundColour('#E5EDF8')
        self.update_size()
        self.allow_via_in_pad.Disable()

    def message(self, text, state='pending'):
        self.status.SetForegroundColour(self.host.colors[state])
        self.status.SetLabel(text)
        self.Layout()

    def invalidate(self, event=None):
        self.preview = self.canvas.preview = None
        self.apply.Enable(False)
        self.canvas.Refresh()
        if event:
            event.Skip()

    def task(self, fn, done):
        if not self.native:
            self.message('Reopen TraceForge using the native PCB Editor button.', 'error')
            return
        self.host.submit_stitching(fn, done, self)

    def preset(self):
        index = self.source.GetSelection()
        return ('active', 'netclass', 'custom')[index] if index < 3 else str(index - 2)

    def update_size(self):
        custom = self.source.GetSelection() == 2
        for key in ('diameter', 'drill'):
            self.fields[key].Enable(custom)
        if not self.data or custom:
            return
        preset = self.preset()
        index = (self.data['active'] if preset == 'active' else
                 int(preset) if preset.isdigit() else 0)
        if not 0 <= index < len(self.data['presets']):
            self.message('Via preset is unavailable. Analyze again or choose Custom.', 'warning')
            return
        dims = (self.data['presets'][index] if index else
                [self.data['defaults']['diameter'], self.data['defaults']['drill']])
        for key, value in zip(('diameter', 'drill'), dims):
            self.fields[key].ChangeValue(f'{value:g}')

    def changed(self, event):
        self.update_size()
        self.escape_layer.Enable(self.mode.GetSelection() == 2)
        self.allow_via_in_pad.Enable(self.mode.GetSelection() == 1)
        self.apply.SetLabel('Apply escaped routes' if self.mode.GetSelection() == 2 else
                            'Apply accepted breakouts')
        self.settings_changed(event)

    def settings_changed(self, event):
        self.invalidate(event)
        self.update_fit()

    def update_fit(self):
        if not self.data:
            return
        try:
            fit = fit_guidance(self.data, self.values())
        except ValueError as exc:
            self.fit.SetLabel(f'Fit: {exc}')
            self.fit.SetForegroundColour(self.host.colors['warning'])
            return
        if fit['reasons']:
            self.fit.SetLabel('Fit review: ' + '\n'.join(fit['reasons'][:3]) +
                              '\nPreview checks actual copper, zones and board edges.')
            self.fit.SetForegroundColour(self.host.colors['warning'])
        else:
            self.fit.SetLabel(
                f'Nominal fit: {fit["selected"]} selected pads; '
                f'{fit["channel_width"]:.3f} mm straight channel, '
                f'{fit["via_gap_limit"]:.3f} mm diagonal via limit. '
                'Preview checks actual obstacles.')
            self.fit.SetForegroundColour(self.host.colors['ok'])
        self.Layout()

    def on_refresh(self, event=None):
        self.task(lambda: self.native('fanout_analyze'), self.accept_data)

    def accept_data(self, data):
        self.invalidate()
        first = self.data is None
        self.data = self.canvas.data = data
        choices = [layer for layer in data['copper_layers'] if layer != data['layer']]
        old_layer = self.escape_layer.GetStringSelection()
        self.escape_layer.Set(choices)
        default_layer = 'B.Cu' if data['layer'] == 'F.Cu' else 'F.Cu'
        self.escape_layer.SetStringSelection(old_layer if old_layer in choices else default_layer)
        self.escape_layer.Enable(self.mode.GetSelection() == 2)
        self.remove.Enable(bool(data.get('managed_items')))
        old = self.source.GetSelection()
        self.source.Set(['Active board preset', 'Netclass per net', 'Custom'] +
                        [f'Preset {i}: {d:g} / {h:g} mm'
                         for i, (d, h) in enumerate(data['presets'][1:], 1)])
        self.source.SetSelection(min(old, self.source.GetCount() - 1))
        if first:
            for key, value in data['defaults'].items():
                self.fields[key].ChangeValue(str(value))
        self.update_size()
        grid = data['grid']
        layout = (f"{grid['columns']} X / {grid['rows']} Y bands; minimum local "
                  f"pitch {grid['pitch_x']:.3f} x {grid['pitch_y']:.3f} mm; variable spacing"
                  if grid['variable_pitch'] else
                  f"{grid['columns']} x {grid['rows']}; pitch "
                  f"{grid['pitch_x']:.3f} x {grid['pitch_y']:.3f} mm")
        self.summary.SetLabel(f"{data['reference']} - {len(data['pads'])} pads; "
                              f"{layout}; {data['layer']}")
        self.canvas.Refresh()
        self.update_fit()
        self.message('Review fabrication limits and sizes, then Preview. '
                     f"{data.get('managed_items', 0)} removable generated items; "
                     f"{data.get('modified_items', 0)} edited/locked items preserved.")

    def values(self):
        mode = ('dogbone', 'via-in-pad', 'auto-escape')[self.mode.GetSelection()]
        return validate(dict(**{k: c.GetValue() for k, c in self.fields.items()},
                             preset=self.preset(),
                             mode=mode,
                             escape_layer=self.escape_layer.GetStringSelection(),
                             allow_via_in_pad=self.allow_via_in_pad.GetValue(),
                             netclass_width=self.netclass_width.GetValue()))

    def on_preview(self, event=None):
        if not self.data:
            self.message('Select a footprint and Analyze selection first.', 'warning')
            return
        try:
            request = dict(footprint=self.data['id'], settings=self.values())
        except ValueError as exc:
            self.message(str(exc), 'error')
            return
        self.invalidate()
        self.task(lambda: self.native('fanout_preview', **request), self.accept_preview)

    def accept_preview(self, result):
        self.preview = self.canvas.preview = result
        self.rows.DeleteAllItems()
        for key, state in (('accepted', 'ok'), ('breakout_only', 'warning'),
                           ('rejected', 'warning'), ('already_routed', 'routed'),
                           ('skipped', 'pending')):
            for row in result[key]:
                i = self.rows.InsertItem(self.rows.GetItemCount(), row['pad'])
                net = row.get('net') or next((p['net'] for p in self.data['pads']
                                               if p['number'] == row['pad']), '')
                self.rows.SetItem(i, 1, net)
                self.rows.SetItem(i, 2, row.get('reason', row.get('status',
                                                               'Accepted pad-to-via breakout')))
                if key in ('accepted', 'breakout_only'):
                    self.rows.SetItem(i, 3, f"{row['diameter']:.3f} / {row['drill']:.3f}")
                self.rows.SetItemTextColour(i, self.host.colors[state])
        count = len(result['accepted'])
        self.apply.Enable(bool(count))
        self.canvas.Refresh()
        self.message(f"{count} accepted; {len(result['breakout_only'])} breakout-only; "
                     f"{len(result['rejected'])} blocked; "
                     f"{len(result['already_routed'])} already routed; "
                     f"{len(result['skipped'])} skipped. Inspect rows before applying.",
                     'ok' if count else 'warning')

    def clear_preview(self, event=None):
        self.invalidate()
        self.message('Preview cleared. The PCB was not changed.')

    def on_apply(self, event):
        if not self.preview:
            return
        token = self.preview['token']
        rejected = len(self.preview['rejected']) + len(self.preview['breakout_only'])
        if rejected and wx.MessageBox(f'{rejected} pads are blocked or only break out.\n'
                                      'Place the accepted routes only?', 'Partial fanout',
                                      wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                                      parent=self) != wx.YES:
            return

        identity = self.data['id']

        def work():
            placed = self.native('fanout_apply', token=token)
            return placed, self.native('fanout_analyze', footprint=identity)

        def done(result):
            placed, data = result
            self.accept_data(data)
            unit = 'escaped routes' if placed['escaped'] else 'pad-to-via breakouts'
            self.message(f"Placed {placed['pads']} {unit}. "
                         'Undo is available in KiCad. '
                         'Run KiCad DRC and save normally.', 'ok')

        self.task(work, done)

    def on_remove(self, event):
        if not self.data:
            return
        count = self.data.get('managed_items', 0)
        if not count:
            self.message('No recorded unchanged fanout remains; manual routing is preserved.',
                         'warning')
            return
        if wx.MessageBox(f"Remove {count} generated tracks/vias for {self.data['reference']}?\n"
                         'Manually edited, locked and untracked copper is preserved.\n'
                         'Removing breakouts may disconnect routing attached to them.',
                         'Remove generated fanout', wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                         parent=self) != wx.YES:
            return
        identity = self.data['id']

        def work():
            removed = self.native('fanout_remove', footprint=identity, expected_count=count)
            return removed, self.native('fanout_analyze', footprint=identity)

        def done(result):
            self.accept_data(result[1])
            self.message(f"Removed {result[0]['removed']} generated items. "
                         'Undo is available in KiCad.', 'ok')

        self.task(work, done)

    def on_suggest(self, event):
        if not self.data:
            self.message('Analyze a selected BGA first.', 'warning')
            return
        try:
            request = dict(footprint=self.data['id'], settings=self.values())
        except ValueError as exc:
            self.message(str(exc), 'error')
            return
        self.invalidate()

        def done(result):
            choices = result['candidates']
            if not choices or not any(c['accepted'] for c in choices):
                self.message('No useful through-via candidate fits these limits. Review the '
                             'pad/pitch, stackup and fabrication process. '
                             'HDI is not auto-selected.',
                             'warning')
                return
            labels = [f"{c['accepted']} accepted / {c['blocked']} blocked — "
                      f"via {c['settings']['diameter']:.3f}/{c['settings']['drill']:.3f} mm, "
                      f"track {c['settings']['width']:.3f} mm; "
                      f"{next(iter(c['reasons']), 'no blocked pads')}" for c in choices]
            dialog = wx.SingleChoiceDialog(self, result['note'] + '\nChoose settings to load; '
                                           'nothing will be placed.', 'Fanout suggestions', labels)
            try:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                chosen = choices[dialog.GetSelection()]['settings']
                self.source.SetSelection(2)
                for key, control in self.fields.items():
                    if key in chosen:
                        control.ChangeValue(str(chosen[key]))
                self.update_size()
                self.invalidate()
                self.message('Suggestion loaded. Review dimensions and Preview before applying.',
                             'ok')
            finally:
                dialog.Destroy()

        self.task(lambda: self.native('fanout_suggest', **request), done)
