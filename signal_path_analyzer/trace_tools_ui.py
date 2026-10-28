"""Trace cleanup and KiCad teardrop access in one tab."""
from __future__ import annotations

import time

import wx

from .trace_cleanup_ui import TraceCleanupPanel


class TeardropDiagram(wx.Panel):
    """Draw the target and the KiCad length/width dimensions beside its toggle."""

    def __init__(self, parent, kind, dark, curved):
        super().__init__(parent, size=(252, 78))
        self.kind, self.curved = kind, curved
        self.background = wx.Colour('#19212D' if dark else '#F2F6FB')
        self.copper = wx.Colour('#E79B45' if dark else '#B8621E')
        self.track = wx.Colour('#79C7E8' if dark else '#146C96')
        self.text = wx.Colour('#D4DFEB' if dark else '#37485A')
        self.SetMinSize((252, 78))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.background))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return
        gc.SetPen(wx.Pen(self.copper, 2))
        gc.SetBrush(wx.Brush(self.copper))
        if self.kind == 'via':
            gc.DrawEllipse(17, 17, 46, 46)
            gc.SetBrush(wx.Brush(self.background))
            gc.DrawEllipse(33, 33, 14, 14)
        elif self.kind == 'pth':
            gc.DrawRoundedRectangle(14, 17, 55, 46, 10)
            gc.SetBrush(wx.Brush(self.background))
            gc.DrawEllipse(33, 33, 14, 14)
        elif self.kind == 'smd':
            gc.DrawRoundedRectangle(13, 18, 58, 44, 5)
        else:
            gc.DrawRoundedRectangle(24, 45, 150, 15, 7)
            gc.DrawRoundedRectangle(93, 12, 14, 48, 6)

        gc.SetPen(wx.Pen(self.track, 2))
        gc.SetBrush(wx.Brush(self.track))
        if self.kind == 'track':
            path = gc.CreatePath()
            path.MoveToPoint(77, 45)
            if self.curved():
                path.AddCurveToPoint(89, 43, 93, 35, 93, 28)
                path.AddLineToPoint(107, 28)
                path.AddCurveToPoint(107, 35, 114, 43, 127, 45)
            else:
                path.AddLineToPoint(93, 28)
                path.AddLineToPoint(107, 28)
                path.AddLineToPoint(127, 45)
            path.CloseSubpath()
            gc.DrawPath(path)
            return
        path = gc.CreatePath()
        path.MoveToPoint(57, 23)
        if self.curved():
            path.AddCurveToPoint(84, 29, 100, 35, 125, 35)
        else:
            path.AddLineToPoint(125, 35)
        path.AddLineToPoint(125, 45)
        if self.curved():
            path.AddCurveToPoint(100, 45, 84, 51, 57, 57)
        else:
            path.AddLineToPoint(57, 57)
        path.CloseSubpath()
        gc.DrawPath(path)
        gc.DrawRoundedRectangle(124, 35, 82, 10, 5)
        if self.kind in ('via', 'pth'):
            gc.SetPen(wx.Pen(self.background, 1))
            gc.SetBrush(wx.Brush(self.background))
            gc.DrawEllipse(33, 33, 14, 14)

        gc.SetPen(wx.Pen(self.text, 1, wx.PENSTYLE_DOT))
        gc.StrokeLine(67, 66, 125, 66)
        gc.StrokeLine(67, 62, 67, 70)
        gc.StrokeLine(125, 62, 125, 70)
        gc.StrokeLine(220, 23, 220, 57)
        gc.StrokeLine(216, 23, 224, 23)
        gc.StrokeLine(216, 57, 224, 57)
        gc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                           wx.FONTWEIGHT_BOLD), self.text)
        gc.DrawText('L', 94, 62)
        gc.DrawText('W', 229, 33)
        gc.DrawText('d', 38, 3)


class TeardropPanel(wx.ScrolledWindow):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.SetScrollRate(0, 12)
        self.host, self.native = host, native
        self.running = False
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label='Set teardrops here, then Apply to the open PCB. '
                                'KiCad generates the shapes and provides Undo.'), 0, wx.ALL, 10)
        columns = wx.BoxSizer(wx.HORIZONTAL)
        left = wx.BoxSizer(wx.VERTICAL)
        self.operation = wx.RadioBox(self, label='Operation', choices=['Add', 'Remove'],
                                     majorDimension=2, style=wx.RA_SPECIFY_COLS)
        self.operation.Bind(wx.EVT_RADIOBOX, self.on_options)
        left.Add(self.operation, 0, wx.EXPAND | wx.BOTTOM, 10)
        self.scope = wx.RadioBox(self, label='Range of application',
                                 choices=['All', 'Selected items'], majorDimension=2,
                                 style=wx.RA_SPECIFY_COLS)
        self.scope.Bind(wx.EVT_RADIOBOX, self.on_options)
        left.Add(self.scope, 0, wx.EXPAND | wx.BOTTOM, 10)
        self.shape = wx.RadioBox(self, label='Shape', choices=['Curved', 'Straight'],
                                 majorDimension=2, style=wx.RA_SPECIFY_COLS)
        self.shape.Bind(wx.EVT_RADIOBOX, self.on_shape)
        left.Add(self.shape, 0, wx.EXPAND | wx.BOTTOM, 10)
        options_box = wx.StaticBox(self, label='Options')
        options = wx.StaticBoxSizer(options_box, wx.VERTICAL)
        self.prefer_zone = wx.CheckBox(options_box, label='Prefer zone connection')
        self.span_two = wx.CheckBox(options_box, label='Allow two track segments')
        self.span_two.SetValue(True)
        options.Add(self.prefer_zone, 0, wx.ALL, 5)
        options.Add(self.span_two, 0, wx.ALL, 5)
        left.Add(options, 0, wx.EXPAND)
        columns.Add(left, 0, wx.EXPAND | wx.RIGHT, 20)

        right = wx.BoxSizer(wx.VERTICAL)
        targets_box = wx.StaticBox(self, label='Where to add teardrops')
        targets = wx.StaticBoxSizer(targets_box, wx.VERTICAL)
        self.vias = wx.CheckBox(targets_box, label='Vias')
        self.pth = wx.CheckBox(targets_box, label='PTH pads')
        self.smd = wx.CheckBox(targets_box, label='SMD pads')
        self.tracks = wx.CheckBox(targets_box, label='Track junctions')
        self.tracks.SetToolTip('KiCad 10 applies Board Setup defaults to track-to-track '
                               'teardrops. Selected-only scope is unavailable for this target.')
        for control in (self.vias, self.pth, self.smd):
            control.SetValue(True)
        self.diagrams = []
        for control, kind, detail in (
                (self.vias, 'via', 'Round via to narrow track'),
                (self.pth, 'pth', 'Through-hole pad to track; pad shape may vary'),
                (self.smd, 'smd', 'Surface pad to narrow track'),
                (self.tracks, 'track', 'T-junction; uses Board Setup defaults')):
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            diagram = TeardropDiagram(targets_box, kind, host.dark,
                                      lambda: self.shape.GetSelection() == 0)
            self.diagrams.append(diagram)
            row.Add(diagram, 0, wx.RIGHT, 8)
            explanation = wx.StaticText(targets_box, label=detail)
            explanation.Wrap(180)
            row.Add(explanation, 1, wx.ALIGN_CENTER_VERTICAL)
            targets.Add(row, 0, wx.EXPAND | wx.ALL, 3)
        right.Add(targets, 0, wx.EXPAND | wx.BOTTOM, 10)
        dimensions_box = wx.StaticBox(self, label='Shared size rule for enabled pads and vias')
        dimensions = wx.StaticBoxSizer(dimensions_box, wx.VERTICAL)
        dimensions.Add(wx.StaticText(dimensions_box,
                                     label='d = pad/via minor size   L = teardrop length   '
                                           'W = teardrop width'), 0, wx.LEFT | wx.TOP, 8)
        grid = wx.FlexGridSizer(cols=3, vgap=7, hgap=8)
        self.fields = {}
        for key, title, default, units in (
                ('track_limit', 'Track width limit', '70', '% of pad/via size'),
                ('length', 'Best length L', '75', '% of pad/via size'),
                ('width', 'Best width W', '35', '% of pad/via size'),
                ('max_length', 'Maximum length', '', 'mm; blank keeps existing'),
                ('max_width', 'Maximum width', '', 'mm; blank keeps existing')):
            grid.Add(wx.StaticText(dimensions_box, label=title), 0,
                     wx.ALIGN_CENTER_VERTICAL)
            field = wx.TextCtrl(dimensions_box, value=default, size=(90, -1))
            self.fields[key] = field
            grid.Add(field)
            grid.Add(wx.StaticText(dimensions_box, label=units), 0,
                     wx.ALIGN_CENTER_VERTICAL)
        dimensions.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        right.Add(dimensions, 0, wx.EXPAND)
        columns.Add(right, 1, wx.EXPAND)
        outer.Add(columns, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(wx.StaticText(self, label='KiCad 10 uses one size rule for pad/via shapes. '
                                'Track-to-track uses Board Setup defaults; apply separately. '
                                'Run DRC after applying.'), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.apply = wx.Button(self, label='Apply to PCB')
        self.apply.Bind(wx.EVT_BUTTON, self.on_apply)
        self.apply.Enable(native is not None)
        actions.Add(self.apply, 0, wx.RIGHT, 8)
        self.open_button = wx.Button(self, label='Open advanced KiCad dialog...')
        self.open_button.Bind(wx.EVT_BUTTON, self.on_open)
        self.open_button.Enable(native is not None)
        actions.Add(self.open_button)
        outer.Add(actions, 0, wx.ALL, 10)
        self.status = wx.StaticText(self, label='Add or remove teardrops with the settings above.')
        outer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)
        self.FitInside()

    def message(self, text, state='pending'):
        self.status.SetForegroundColour(self.host.colors[state])
        self.status.SetLabel(text)

    def invalidate(self):
        self.running = False
        self.apply.Enable(self.native is not None)

    def on_options(self, event):
        adding = self.operation.GetSelection() == 0
        selected = self.scope.GetSelection() == 1
        self.shape.Enable(adding)
        self.prefer_zone.Enable(adding)
        self.span_two.Enable(adding)
        for field in self.fields.values():
            field.Enable(adding)
        if selected:
            self.tracks.SetValue(False)
        self.tracks.Enable(not selected)

    def on_shape(self, event):
        for diagram in self.diagrams:
            diagram.Refresh()

    def settings(self):
        values = {key: field.GetValue().strip() for key, field in self.fields.items()}
        values.update(operation='add' if self.operation.GetSelection() == 0 else 'remove',
                      selected_only=self.scope.GetSelection() == 1,
                      curved=self.shape.GetSelection() == 0,
                      prefer_zone=self.prefer_zone.GetValue(),
                      span_two=self.span_two.GetValue(),
                      vias=self.vias.GetValue(), pth=self.pth.GetValue(),
                      smd=self.smd.GetValue(), tracks=self.tracks.GetValue())
        return values

    def on_apply(self, event=None):
        if self.running or self.native is None:
            return
        if self.host.busy or self.host.actions_pending:
            self.message('Another PCB operation is running. Try Apply when it finishes.', 'warning')
            return
        self.running = True
        self.apply.Disable()
        self.message('Applying teardrops in KiCad...')
        settings = self.settings()

        def started(result):
            token = result['token']

            def poll():
                for _ in range(180):
                    time.sleep(0.25)
                    state = self.native('teardrop_status', token=token)
                    if state['state'] != 'running':
                        return state
                raise TimeoutError('KiCad teardrop operation did not finish.')

            future = self.host.worker.submit(poll)

            def finished(done):
                if self.host.closing:
                    return
                self.running = False
                self.apply.Enable()
                try:
                    state = done.result()
                    self.message(state['message'],
                                 'ok' if state['state'] == 'complete' else 'error')
                except Exception as exc:
                    self.message(str(exc), 'error')

            future.add_done_callback(lambda done: wx.CallAfter(finished, done)
                                     if not self.host.closing else None)

        self.host.submit_stitching(
            lambda: self.native('teardrop_apply', settings=settings),
            started, self)

    def on_open(self, event=None):
        if self.native is None:
            self.message('Native PCB access is unavailable.', 'error')
            return
        self.host.submit_stitching(
            lambda: self.native('visual_teardrops'),
            lambda result: self.message('KiCad Edit Teardrops opened.', 'ok'), self)

    def on_refresh(self, event=None):
        self.message('Set the controls, then click Apply to PCB.')


class FilletPanel(wx.Panel):
    """Batch fillet preview with exact per-corner restore through PCB selection."""

    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        self.token = None
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label='Round existing track corners on every copper layer. '
                                'TraceForge skips branches, pad/via junctions, locked tracks, '
                                'and corners too short for the radius.'), 0, wx.ALL, 10)
        settings = wx.BoxSizer(wx.HORIZONTAL)
        settings.Add(wx.StaticText(self, label='Maximum corner radius (mm)'), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 7)
        self.radius = wx.TextCtrl(self, value='0.5', size=(90, -1))
        settings.Add(self.radius, 0, wx.RIGHT, 15)
        self.scope = wx.Choice(self, choices=['Whole PCB', 'Selected tracks'])
        self.scope.SetSelection(0)
        settings.Add(self.scope, 0, wx.RIGHT, 10)
        self.preview_button = wx.Button(self, label='Preview corners')
        self.preview_button.Bind(wx.EVT_BUTTON, self.on_preview)
        settings.Add(self.preview_button, 0, wx.RIGHT, 8)
        self.apply_button = wx.Button(self, label='Round eligible corners')
        self.apply_button.Disable()
        self.apply_button.Bind(wx.EVT_BUTTON, self.on_apply)
        settings.Add(self.apply_button)
        outer.Add(settings, 0, wx.ALL, 10)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.adaptive = wx.CheckBox(
            self, label='Fit smaller bends when the chosen radius will not fit')
        self.adaptive.SetValue(True)
        filters.Add(self.adaptive, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 20)
        filters.Add(wx.StaticText(self, label='Exact net name (optional)'), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.net = wx.TextCtrl(self, size=(220, -1))
        filters.Add(self.net)
        outer.Add(filters, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        for control, changed in ((self.radius, wx.EVT_TEXT),
                                 (self.net, wx.EVT_TEXT),
                                 (self.scope, wx.EVT_CHOICE),
                                 (self.adaptive, wx.EVT_CHECKBOX)):
            control.Bind(changed, lambda event: self.invalidate())
        restore = wx.BoxSizer(wx.HORIZONTAL)
        self.restore_button = wx.Button(self, label='Restore selected rounded corner(s)')
        self.restore_button.Bind(wx.EVT_BUTTON, lambda event: self.on_restore('selected'))
        restore.Add(self.restore_button, 0, wx.RIGHT, 10)
        self.restore_all_button = wx.Button(self, label='Restore all rounded corners')
        self.restore_all_button.Bind(wx.EVT_BUTTON, lambda event: self.on_restore('all'))
        restore.Add(self.restore_all_button, 0, wx.RIGHT, 10)
        restore.Add(wx.StaticText(
            self, label='Select a generated arc or adjacent track for selective restore.'),
                    0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(restore, 0, wx.ALL, 10)
        self.summary = wx.StaticText(self, label='Choose a radius, then Preview corners.')
        outer.Add(self.summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.details = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.details, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(wx.StaticText(self, label='This changes copper geometry and track lengths. '
                                'Save the PCB and run KiCad DRC after applying. '
                                'KiCad Undo is also available.'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)

    def message(self, text, state='pending'):
        self.summary.SetForegroundColour(self.host.colors[state])
        self.summary.SetLabel(text)

    def invalidate(self):
        self.token = None
        self.apply_button.Disable()

    def on_preview(self, event=None):
        self.invalidate()
        scope = 'all' if self.scope.GetSelection() == 0 else 'selected'
        radius = self.radius.GetValue().strip()
        adaptive = self.adaptive.GetValue()
        net = self.net.GetValue().strip()

        def done(result):
            self.token = result['token']
            self.apply_button.Enable(bool(result['accepted']))
            self.message(f"{result['accepted']} corners eligible "
                         f"({result['adjusted']} fitted to smaller radii); "
                         f"{result['skipped']} skipped; "
                         f"{result['existing']} existing TraceForge fillets.",
                         'ok' if result['accepted'] else 'warning')
            lines = ['Skipped by reason:']
            lines.extend(f'  {reason}: {count}' for reason, count in
                         sorted(result['reasons'].items(), key=lambda item: -item[1]))
            lines.append('')
            lines.extend(f"{row['layer']}  {row['net']}  "
                         f"({row['point'][0]}, {row['point'][1]} mm): {row['reason']}"
                         for row in result['examples'])
            if result['skipped'] > len(lines):
                lines.append(f"...and {result['skipped'] - len(lines)} more skipped corners")
            self.details.SetValue('\n'.join(lines))

        self.host.submit_stitching(
            lambda: self.native('fillet_preview', radius=radius, scope=scope,
                                adaptive=adaptive, net=net), done, self)

    def on_apply(self, event=None):
        if not self.token:
            self.message('Preview the current PCB first.', 'warning')
            return
        token = self.token
        self.invalidate()

        def done(result):
            self.host.refresh_policy.invalidate()
            self.message(f"Rounded {result['added']} corners. Save the PCB and run DRC.", 'ok')

        self.host.submit_stitching(lambda: self.native('fillet_apply', token=token), done, self)

    def on_restore(self, scope='selected'):
        self.invalidate()

        def done(result):
            self.host.refresh_policy.invalidate()
            self.message(f"Restored {result['restored']} original corner(s).", 'ok')

        self.host.submit_stitching(lambda: self.native('fillet_restore', scope=scope), done, self)

    def on_refresh(self, event=None):
        self.invalidate()
        self.message('Set a radius and Preview again after PCB changes.')


class TraceToolsPanel(wx.Panel):
    names = ('Trace Cleanup', 'Teardrops', 'Round Corners')

    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host = host
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        outer = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        bar.AddStretchSpacer()
        bar.Add(wx.StaticText(self, label='Trace tool:'), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.selector = wx.Choice(self, choices=list(self.names), size=(160, -1))
        self.selector.SetSelection(0)
        self.selector.SetToolTip('Switch between cleanup, teardrops, and rounded trace corners.')
        self.selector.Bind(wx.EVT_CHOICE, self.on_choice)
        bar.Add(self.selector)
        outer.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
        self.book = wx.Simplebook(self)
        self.cleanup = TraceCleanupPanel(self.book, host, native)
        self.teardrops = TeardropPanel(self.book, host, native)
        self.fillets = FilletPanel(self.book, host, native)
        self.book.AddPage(self.cleanup, self.names[0])
        self.book.AddPage(self.teardrops, self.names[1])
        self.book.AddPage(self.fillets, self.names[2])
        outer.Add(self.book, 1, wx.EXPAND)
        self.SetSizer(outer)

    @property
    def active_index(self):
        return self.selector.GetSelection()

    @property
    def active_page(self):
        return (self.cleanup, self.teardrops, self.fillets)[self.active_index]

    def on_choice(self, event):
        self.book.SetSelection(self.active_index)
        self.host.schedule_auto_refresh()
