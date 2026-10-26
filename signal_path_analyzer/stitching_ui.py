"""Via stitching form, board-overview drawing and non-destructive placement preview."""
from __future__ import annotations

from collections import Counter

import wx

from .stitching import polygon, rectangle, settings


class BoardOverview(wx.Panel):
    def __init__(self, parent, changed, colors):
        super().__init__(parent)
        self.changed, self.colors = changed, colors
        self.scene, self.preview, self.region = None, None, None
        self.mode, self.vertices, self.start, self.hover = None, [], None, None
        self.SetMinSize((300, 210))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_LEFT_DOWN, self.left_down)
        self.Bind(wx.EVT_LEFT_UP, self.left_up)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.capture_lost)
        self.Bind(wx.EVT_MOTION, self.motion)
        self.Bind(wx.EVT_LEFT_DCLICK, self.finish)
        self.Bind(wx.EVT_RIGHT_DOWN, self.finish)
        self.Bind(wx.EVT_KEY_DOWN, self.key)

    def transform(self):
        points = [p for rings in self.scene['outline'] for p in rings[0]] if self.scene else []
        if getattr(self.GetParent(), 'trace_mode', False) and self.region:
            points = self.region.get('points', []) + (
                [p[:2] for key in ('accepted', 'rejected') for p in self.preview[key]]
                if self.preview else [])
            if points:
                xs, ys = zip(*points)
                points = points + [[min(xs) - 2, min(ys) - 2], [max(xs) + 2, max(ys) + 2]]
        if not points:
            return (0, 0, 1, 12, 12)
        xs, ys = zip(*points)
        size = self.GetClientSize()
        scale = min(max(size.width - 24, 1) / max(max(xs) - min(xs), 1),
                    max(size.height - 24, 1) / max(max(ys) - min(ys), 1))
        return min(xs), min(ys), scale, 12, 12

    def world(self, pos):
        x0, y0, scale, ox, oy = self.transform()
        return [round(x0 + (pos.x - ox) / scale, 3),
                round(y0 + (pos.y - oy) / scale, 3)]

    def screen(self, point):
        x0, y0, scale, ox, oy = self.transform()
        return wx.Point(round((point[0] - x0) * scale + ox),
                        round((point[1] - y0) * scale + oy))

    def begin(self, mode):
        if not self.scene:
            return
        if self.HasCapture():
            self.ReleaseMouse()
        self.mode, self.vertices, self.start, self.hover = mode, [], None, None
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.SetFocus()
        self.Refresh()

    def left_down(self, event):
        if not self.mode:
            return
        self.SetFocus()
        p = self.world(event.GetPosition())
        if self.mode == 'rectangle':
            self.start = p
            if not self.HasCapture():
                self.CaptureMouse()
        elif not self.vertices or self.vertices[-1] != p:
            self.vertices.append(p)
        self.hover = p
        self.Refresh()

    def left_up(self, event):
        if self.mode == 'rectangle' and self.start is not None:
            a, b = self.start, self.world(event.GetPosition())
            if self.HasCapture():
                self.ReleaseMouse()
            try:
                self.complete(rectangle(a, b))
            except ValueError as exc:
                self.start = None
                wx.MessageBox(str(exc), 'Stitching region', parent=self)

    def capture_lost(self, event):
        self.start = self.hover = None
        self.Refresh()
        event.Skip()

    def motion(self, event):
        if self.mode:
            self.hover = self.world(event.GetPosition())
            self.Refresh()

    def finish(self, event):
        if self.mode == 'polygon' and len(self.vertices) >= 3:
            self.complete(self.vertices)

    def key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            if self.HasCapture():
                self.ReleaseMouse()
            self.mode, self.vertices, self.start = None, [], None
            self.SetCursor(wx.NullCursor)
            self.Refresh()
        elif event.GetKeyCode() == wx.WXK_RETURN:
            self.finish(event)
        else:
            event.Skip()

    def complete(self, points):
        try:
            points = polygon(points)
        except ValueError as exc:
            wx.MessageBox(str(exc), 'Stitching region', parent=self)
            return
        self.region = dict(kind='polygon', points=points)
        self.mode, self.vertices, self.start = None, [], None
        self.SetCursor(wx.NullCursor)
        self.changed(self.region)
        self.Refresh()

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dark = self.GetTopLevelParent().dark
        dc.SetBackground(wx.Brush('#19212D' if dark else '#FFFFFF'))
        dc.Clear()
        if not self.scene:
            dc.SetTextForeground(self.colors['pending'])
            dc.DrawText('Click Refresh board to load the board overview.', 12, 12)
            return
        x0, y0, scale, ox, oy = self.transform()

        def screen(point):
            return wx.Point(round((point[0] - x0) * scale + ox),
                            round((point[1] - y0) * scale + oy))

        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(self.colors['pending'], 1))
        for rings in self.scene['outline']:
            for ring in rings:
                if ring:
                    pts = [screen(p) for p in ring]
                    dc.DrawLines(pts + pts[:1])
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(self.colors['routed']))
        for group in self.scene.get('sets', []):
            coordinates_list = list((group.get('record') or {}).get('vias', {}).values())
            stride = max(1, (len(coordinates_list) + 4999) // 5000)
            for coordinates in coordinates_list[::stride]:
                dc.DrawCircle(screen(coordinates), 2)
        if self.preview:
            for key, state in (('rejected', 'warning'), ('accepted', 'ok')):
                dc.SetBrush(wx.Brush(self.colors[state]))
                points = self.preview[key]
                # Keep the overview responsive on a dense, full-board grid. All
                # sites remain in the preview and are checked when applying.
                stride = max(1, (len(points) + 4999) // 5000)
                for p in points[::stride]:
                    dc.DrawCircle(screen(p), 2 if key == 'rejected' else 3)
        region = (self.region or {}).get('points', [])
        if self.mode == 'rectangle' and self.start and self.hover:
            a, b = self.start, self.hover
            try:
                region = rectangle(a, b)
            except ValueError:
                region = []
        elif self.mode == 'polygon':
            region = self.vertices + ([self.hover] if self.hover else [])
        if len(region) > 1:
            dc.SetPen(wx.Pen(self.colors['routed'], 2))
            pts = [screen(p) for p in region]
            dc.DrawLines(pts if self.mode == 'polygon' or (self.region or {}).get(
                'kind') == 'trace' else pts + pts[:1])
            if (self.region or {}).get('kind') == 'trace':
                dc.SetTextForeground(self.colors['routed'])
                dc.DrawText('Start', pts[0].x + 4, pts[0].y + 4)


class StitchingPanel(wx.Panel):
    def __init__(self, parent, host, native, trace_mode=False):
        super().__init__(parent)
        if host.dark:
            self.SetBackgroundColour('#222C3A')
            self.SetForegroundColour('#E5EDF8')
        self.host, self.native, self.scene = host, native, None
        self.trace_mode = trace_mode
        self.preview, self.region, self.replace = None, dict(kind='board'), None
        self.identities, self.loaded, self.filling = [], False, False
        outer = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        toolbar = (('Refresh board (F5)', self.on_refresh),
                              ('Use PCB selection', self.on_selected),
                              ('Draw rectangle', lambda event: self.draw('rectangle')),
                              ('Draw polygon', lambda event: self.draw('polygon')),
                              ('Whole board', self.on_whole))
        if trace_mode:
            toolbar = (('Refresh fence sets (F5)', self.on_refresh),
                       ('Use selected trace', self.on_selected))
        for text, handler in toolbar:
            button = wx.Button(self, label=text, style=wx.BU_EXACTFIT)
            button.Bind(wx.EVT_BUTTON, handler)
            bar.Add(button, 0, wx.RIGHT, 5)
        outer.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
        if not trace_mode:
            outer.Add(wx.StaticText(self, label='X/Y spacing is the via-center grid pitch. '
                                    'Preview skips blocked sites without changing the pitch.'),
                      0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        body = wx.BoxSizer(wx.HORIZONTAL)
        form = wx.FlexGridSizer(cols=2, vgap=5, hgap=8)
        self.advanced_rows = []
        self.name = wx.TextCtrl(self, value='RF trace fence' if trace_mode else 'Ground stitching')
        self.net = wx.ComboBox(self, style=wx.CB_DROPDOWN if trace_mode else wx.CB_READONLY)
        self.source = wx.Choice(self, choices=['Active board preset', 'Netclass', 'Custom'])
        self.source.SetSelection(0)
        self.connection = wx.Choice(self, choices=['At least two copper layers',
                                                  'Every copper layer'])
        self.connection.SetSelection(0)
        self.pattern = wx.Choice(self, choices=['Symmetric (aligned rows)',
                                               'Staggered (alternate rows offset)',
                                               'Perimeter fence'])
        self.pattern.SetSelection(0)
        if trace_mode:
            self.pattern.Set(['Both sides', 'Left side', 'Right side'])
            self.pattern.SetSelection(0)
        for label, control in (('Set name', self.name), ('Net', self.net),
                               ('Via size source', self.source),
                               ('Fence side' if trace_mode else 'Placement pattern', self.pattern),
                               ('Copper contact', self.connection)):
            caption = wx.StaticText(self, label=label)
            form.Add(caption, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
            if not trace_mode and control in (self.name, self.pattern, self.connection):
                self.advanced_rows.append((caption, control))
        self.fields = {}
        fields = [('diameter', 'Via diameter (mm)', '.6'),
                                  ('drill', 'Drill diameter (mm)', '.25'),
                                  ('pitch_x', 'Spacing X (mm)', '5'),
                                  ('pitch_y', 'Spacing Y (mm)', '5'),
                                  ('offset_x', 'Grid offset X (mm)', '0'),
                                  ('offset_y', 'Grid offset Y (mm)', '0'),
                                  ('boundary', 'Region/copper setback (mm)', '.2'),
                                  ('edge', 'Board-edge setback (mm)', '.5')]
        if trace_mode:
            fields.append(('trace_gap', 'Copper gap to signal trace (mm)', '.3'))
        for key, label, value in fields:
            if trace_mode and key == 'pitch_x':
                label = 'Spacing along trace (mm)'
            elif not trace_mode and key in ('pitch_x', 'pitch_y'):
                label = f"Spacing {'X' if key == 'pitch_x' else 'Y'} center-to-center (mm)"
            if trace_mode and key == 'boundary':
                label, value = 'Copper-fill setback (mm)', '0'
            control = wx.TextCtrl(self, value=value, size=(100, -1))
            self.fields[key] = control
            if trace_mode and key in ('pitch_y', 'offset_x', 'offset_y'):
                control.Hide()
            else:
                caption = wx.StaticText(self, label=label)
                form.Add(caption, 0, wx.ALIGN_CENTER_VERTICAL)
                form.Add(control, 1, wx.EXPAND)
                if not trace_mode and key in ('offset_x', 'offset_y', 'boundary', 'edge'):
                    self.advanced_rows.append((caption, control))
            control.Bind(wx.EVT_TEXT, self.invalidate)
        form.AddGrowableCol(1)
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(form, 0, wx.EXPAND)
        self.advanced = None
        if not trace_mode:
            self.advanced = wx.CheckBox(self, label='Advanced options')
            self.advanced.Bind(wx.EVT_CHECKBOX, self.toggle_advanced)
            left.Add(self.advanced, 0, wx.TOP, 8)
        body.Add(left, 0, wx.ALL, 6)
        right = wx.BoxSizer(wx.VERTICAL)
        self.region_label = wx.StaticText(self, label='Region: Whole board')
        right.Add(self.region_label, 0, wx.BOTTOM, 4)
        instructions = ('Blue: signal path. Both sides places a via row along each side. '
                        'Start marks left/right.'
                        if trace_mode else 'Board overview: drag a rectangle; click polygon '
                        'vertices, then Enter/right-click. Esc cancels.')
        right.Add(wx.StaticText(self, label=instructions), 0, wx.BOTTOM, 4)
        self.canvas = BoardOverview(self, self.set_region, host.colors)
        right.Add(self.canvas, 1, wx.EXPAND)
        self.counts = wx.StaticText(self, label='Green: accepted   Amber: skipped   '
                                   'Blue: existing sets')
        right.Add(self.counts, 0, wx.TOP, 4)
        body.Add(right, 1, wx.EXPAND | wx.ALL, 6)
        outer.Add(body, 1, wx.EXPAND)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.apply = wx.Button(self, label='Apply trace fence' if trace_mode else 'Apply stitching')
        self.apply.Enable(False)
        for text, handler in (('Preview', self.on_preview), ('Clear preview', self.clear_preview)):
            button = wx.Button(self, label=text)
            button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 5)
        self.apply.Bind(wx.EVT_BUTTON, self.on_apply)
        actions.Add(self.apply, 0, wx.RIGHT, 12)
        actions.Add(wx.StaticText(self, label='Conservative geometry checks; run KiCad DRC '
                                 'after placement to check custom rules.'),
                    0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(actions, 0, wx.ALL, 6)
        self.sets = wx.ListCtrl(self, style=wx.LC_REPORT, size=(-1, 105))
        for i, (label, width) in enumerate((('Stitching set', 230), ('Net', 170),
                                           ('Vias', 65), ('Status', 280))):
            self.sets.InsertColumn(i, label, width=width)
        outer.Add(self.sets, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        manage = wx.BoxSizer(wx.HORIZONTAL)
        for text, handler in (('Select set', lambda event: self.select(False)),
                              ('Select all stitching', lambda event: self.select(True)),
                              ('Edit / regenerate', self.on_edit),
                              ('Remove set', lambda event: self.remove(False)),
                              ('Remove all stitching', lambda event: self.remove(True))):
            if trace_mode:
                text = text.replace('stitching', 'fences')
            button = wx.Button(self, label=text, style=wx.BU_EXACTFIT)
            button.Bind(wx.EVT_BUTTON, handler)
            manage.Add(button, 0, wx.RIGHT, 5)
        outer.Add(manage, 0, wx.ALL, 6)
        self.status = wx.StaticText(self, label='Click Refresh board to begin. '
                                   'No automatic polling.')
        self.status.SetForegroundColour(host.colors['pending'])
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(outer)
        self.toggle_advanced()
        if host.dark:
            self.sets.SetBackgroundColour('#19212D')
            self.sets.SetForegroundColour('#E5EDF8')
            for child in self.GetChildren():
                if isinstance(child, wx.StaticText) and child is not self.status:
                    child.SetForegroundColour('#E5EDF8')
        for control in (self.name, self.net, self.source, self.connection, self.pattern):
            control.Bind(wx.EVT_TEXT if control is self.name or
                         (trace_mode and control is self.net) else wx.EVT_CHOICE
                         if control in (self.source, self.connection, self.pattern)
                         else wx.EVT_COMBOBOX,
                         self.changed)

    def message(self, text, state='pending'):
        self.status.SetForegroundColour(self.host.colors[state])
        self.status.SetLabel(text)
        self.Layout()

    def toggle_advanced(self, event=None):
        if self.advanced is not None:
            visible = self.advanced.GetValue()
            for caption, control in self.advanced_rows:
                caption.Show(visible)
                control.Show(visible)
            self.Layout()
        if event:
            event.Skip()

    def task(self, fn, done):
        if self.native is None:
            self.message('Native stitching access is unavailable. Reopen TraceForge from KiCad.',
                         'error')
            return
        self.host.submit_stitching(fn, done, self)

    def invalidate(self, event=None):
        if not self.filling:
            self.preview, self.canvas.preview = None, None
            self.apply.Enable(False)
            self.canvas.Refresh()
            if self.scene:
                self.message('Settings changed. Click Preview before applying.')
        if event:
            event.Skip()

    def changed(self, event):
        self.update_sizes()
        self.update_pattern()
        self.invalidate(event)

    def update_pattern(self):
        fence = self.pattern.GetSelection() == 2
        for key in ('pitch_y', 'offset_x', 'offset_y'):
            self.fields[key].Enable(not fence)
        self.fields['pitch_x'].SetToolTip('Fence: maximum distance along the inset perimeter. '
                                        'Grid: horizontal center-to-center spacing.')

    def size_source(self):
        i = self.source.GetSelection()
        return ('board', 'netclass', 'custom')[i] if i < 3 else f'preset:{i - 2}'

    def update_sizes(self):
        custom = self.source.GetSelection() == 2
        for key in ('diameter', 'drill'):
            self.fields[key].Enable(custom)
        if not self.scene or custom:
            return
        source = self.size_source()
        index = self.scene['active_preset'] if source == 'board' else 0
        if source.startswith('preset:'):
            index = int(source.split(':')[1])
        if not 0 <= index < len(self.scene['presets']):
            self.message('Via preset is unavailable. Refresh board or choose Custom.', 'warning')
            return
        dims = (self.scene['presets'][index] if index else
                self.scene['nets'].get(self.net.GetValue(), [0, 0]))
        for key, value in zip(('diameter', 'drill'), dims):
            self.fields[key].ChangeValue(f'{value:g}')

    def collect(self):
        values = {k: v.GetValue() for k, v in self.fields.items()}
        pattern = ('symmetric', 'staggered', 'fence')[self.pattern.GetSelection()]
        if pattern == 'fence':
            values.update(pitch_y=values['pitch_x'], offset_x='0', offset_y='0')
        return settings(dict(net=self.net.GetValue(), size_source=self.size_source(),
                             pattern=pattern,
                             connection='all' if self.connection.GetSelection() else 'two',
                             **values))

    def set_region(self, region):
        self.region = region
        self.canvas.region = region
        self.canvas.mode, self.canvas.vertices, self.canvas.start = None, [], None
        self.canvas.SetCursor(wx.NullCursor)
        self.region_label.SetLabel('Region: ' + {'board': 'Whole board',
                                                'zone': 'Selected copper zone',
                                                'shape': 'Selected PCB drawing',
                                                'polygon': 'Drawn region'}[region['kind']])
        self.invalidate()

    def draw(self, mode):
        if self.scene:
            self.invalidate()
            self.canvas.begin(mode)
            self.message(f'Draw the {mode} on the board overview. Esc cancels.')
        else:
            self.message('Click Refresh board before drawing a region.', 'warning')

    def on_whole(self, event):
        self.replace = None
        self.apply.SetLabel('Apply stitching')
        self.set_region(dict(kind='board'))

    def on_refresh(self, event=None):
        self.task(lambda: self.native('stitch_scene'), self.accept_scene)

    def on_selected(self, event):
        def accept(scene):
            self.accept_scene(scene)
            if scene['selected_region']:
                self.set_region(scene['selected_region'])
                if self.region.get('net'):
                    self.net.SetValue(self.region['net'])
                    self.update_sizes()
            else:
                self.message(scene.get('selection_error') or
                             'Select one copper zone, rectangle or polygon in PCB Editor.',
                             'warning')
        self.task(lambda: self.native('stitch_scene'), accept)

    def fill(self, saved, restore_advanced=False):
        self.filling = True
        try:
            values = saved.get('settings', {})
            if not restore_advanced and not self.trace_mode:
                # Remember the everyday inputs without carrying a hidden strict
                # contact or setback setting into a new placement.
                values = {k: v for k, v in values.items()
                          if k in ('net', 'size_source', 'diameter', 'drill',
                                   'pitch_x', 'pitch_y')}
            self.name.ChangeValue(saved.get('name', 'Ground stitching'))
            self.net.SetValue(values.get('net', 'GND' if 'GND' in self.scene['nets'] else
                                         next(iter(self.scene['nets']), '')))
            source = values.get('size_source', 'board')
            index = {'board': 0, 'netclass': 1, 'custom': 2}.get(source, 0)
            if source.startswith('preset:'):
                index = min(int(source.split(':')[1]) + 2, self.source.GetCount() - 1)
            self.source.SetSelection(index)
            self.connection.SetSelection(int(values.get('connection') == 'all'))
            self.pattern.SetSelection({'symmetric': 0, 'staggered': 1, 'fence': 2}.get(
                values.get('pattern'), 0))
            self.update_pattern()
            for key, control in self.fields.items():
                if key in values:
                    control.ChangeValue(str(values[key]))
            self.set_region(saved.get('region', dict(kind='board')))
            self.update_sizes()
            if self.advanced is not None:
                self.advanced.SetValue(bool(restore_advanced))
                self.toggle_advanced()
        finally:
            self.filling = False

    def accept_scene(self, scene):
        selected = set(self.selected_ids()) if self.scene else set()
        top = self.sets.GetTopItem()
        self.invalidate()
        self.scene = self.canvas.scene = scene
        previous = self.net.GetValue()
        self.net.Set(sorted(scene['nets']))
        self.net.SetValue(previous if previous in scene['nets'] else
                          'GND' if 'GND' in scene['nets'] else next(iter(scene['nets']), ''))
        old_source = self.source.GetSelection()
        self.source.Set(['Active board preset', 'Netclass', 'Custom'] +
                        [f'Board preset {i}: {d:g} / {h:g} mm'
                         for i, (d, h) in enumerate(scene['presets'][1:], 1)])
        self.source.SetSelection(min(old_source, self.source.GetCount() - 1))
        self.sets.DeleteAllItems()
        self.identities = []
        for group in scene['sets']:
            row = self.sets.InsertItem(self.sets.GetItemCount(), group['name'])
            for col, text in enumerate((group['net'], str(group['count']), group['status'] +
                                       (f"; {group['extra']} unmanaged members preserved"
                                        if group['extra'] else '')), 1):
                self.sets.SetItem(row, col, text)
            self.identities.append(group['id'])
            if group['id'] in selected:
                self.sets.Select(row)
        if self.sets.GetItemCount() and top >= 0:
            self.sets.EnsureVisible(min(top, self.sets.GetItemCount() - 1))
        if not self.loaded:
            self.fill(scene.get('last', {}))
            self.loaded = True
        self.update_sizes()
        self.canvas.Refresh()
        self.message(f"Board loaded. {len(scene['sets'])} stitching sets. Draw or choose a region.")

    def on_preview(self, event=None):
        if not self.scene:
            self.message('Click Refresh board first.', 'warning')
            return
        if self.canvas.mode:
            self.message('Finish or cancel region drawing before previewing.', 'warning')
            return
        try:
            request = dict(settings=self.collect(), region=self.region, replace=self.replace,
                           name=self.name.GetValue().strip() or 'Ground stitching')
        except ValueError as exc:
            self.message(str(exc), 'error')
            return
        self.invalidate()
        self.task(lambda: self.native('stitch_preview', **request), self.accept_preview)

    def accept_preview(self, result):
        if self.trace_mode:
            self.region = self.canvas.region = result['region']
        self.preview = self.canvas.preview = result
        for key in ('diameter', 'drill'):
            self.fields[key].ChangeValue(str(result['settings'][key]))
        self.canvas.Refresh()
        count = len(result['accepted'])
        reasons = '; '.join(f'{key}: {value}' for key, value in result['reasons'].items())
        self.counts.SetLabel(f"Accepted: {count}   Skipped: {len(result['rejected'])}")
        self.apply.Enable(bool(count))
        fence = result.get('fence')
        gap = (f" Largest fence gap: {fence['largest_gap_mm']:.3f} mm; requested "
               f"{fence['spacing_mm']:.3f} mm." if fence else '')
        broken = fence and fence['largest_gap_mm'] > fence['spacing_mm'] * 1.01
        self.message(f"{count} accepted. {reasons or 'No rejected locations.'}{gap}",
                     'ok' if count and not broken else 'warning')

    def clear_preview(self, event=None):
        self.invalidate()
        self.message('Preview cleared. The board was not changed.')

    def on_apply(self, event):
        if not self.preview:
            return
        token = self.preview['token']

        def work():
            result = self.native('stitch_apply', token=token)
            return result, self.native('stitch_scene')

        def done(result):
            self.replace = None
            self.apply.SetLabel('Apply trace fence' if self.trace_mode else 'Apply stitching')
            self.accept_scene(result[1])
            self.message(f"Placed {result[0]['count']} stitching vias. Undo is available in KiCad; "
                         'save the PCB normally.', 'ok')

        self.task(work, done)

    def selected_ids(self, all_sets=False):
        if all_sets:
            return [g['id'] for g in (self.scene or {}).get('sets', []) if g['record']]
        chosen, index = [], self.sets.GetFirstSelected()
        while index != -1:
            chosen.append(self.identities[index])
            index = self.sets.GetNextSelected(index)
        return chosen

    def select(self, all_sets):
        ids = self.selected_ids(all_sets)
        if not ids:
            self.message('Choose a managed stitching set first.', 'warning')
            return
        self.task(lambda: self.native('stitch_select', ids=ids),
                  lambda count: self.message(f'Selected {count} managed stitching vias in KiCad.',
                                             'routed'))

    def on_edit(self, event):
        ids = self.selected_ids()
        if len(ids) != 1:
            self.message('Choose exactly one stitching set to edit.', 'warning')
            return
        group = next(g for g in self.scene['sets'] if g['id'] == ids[0])
        if not group['record']:
            self.message('Settings metadata is missing for this set.', 'error')
            return
        self.fill(group['record'], restore_advanced=True)
        self.replace = ids[0]
        self.apply.SetLabel('Replace selected set')
        self.invalidate()
        self.message('Edit settings or redraw the region, then Preview and Replace selected set.')

    def remove(self, all_sets):
        ids = self.selected_ids(all_sets)
        if not ids:
            self.message('Choose a managed stitching set first.', 'warning')
            return
        counts = Counter({g['id']: g['count'] for g in self.scene['sets']})
        count = sum(counts[k] for k in ids)
        if wx.MessageBox(f'Remove {count} managed stitching vias from {len(ids)} sets?\n'
                         'Ordinary routing vias and unmanaged group members are preserved.',
                         'Remove stitching', wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                         parent=self) != wx.YES:
            return

        def work():
            count = self.native('stitch_remove', ids=ids)
            return count, self.native('stitch_scene')

        def done(result):
            self.accept_scene(result[1])
            self.message(f'Removed {result[0]} stitching vias. Undo is available in KiCad.', 'ok')

        self.task(work, done)
