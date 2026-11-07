"""Filter, select, delete and DRC-preview larger vias from Via Tools."""
from __future__ import annotations

import wx

from .via_manager import PRESETS, analyze


class ViaSizePreview(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows = []
        self.target = None
        self.SetMinSize((-1, 220))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))

    def show(self, rows, target=None):
        self.rows = rows
        self.target = target
        self.Refresh()

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush('#19212D'))
        dc.Clear()
        dc.SetTextForeground(wx.Colour('#E5EDF8'))
        dc.DrawText('Green: can grow   Red: blocked   Gray: skipped | select row to focus PCB',
                    12, 9)
        if not self.rows:
            return
        size = self.GetClientSize()
        xs = [r['x_mm'] for r in self.rows]
        ys = [r['y_mm'] for r in self.rows]
        cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
        scale = min(max(1, size.width-50)/max(max(xs)-min(xs)+2, 2),
                    max(1, size.height-70)/max(max(ys)-min(ys)+2, 2))
        for row in self.rows:
            color = {'ready': '#54D7A2', 'blocked': '#F36C6C',
                     'candidate': '#F5B95D'}.get(row['status'], '#8C9AAB')
            x = round(size.width/2 + (row['x_mm']-cx)*scale)
            y = round((size.height+30)/2 + (row['y_mm']-cy)*scale)
            proposed = self.target if self.target and row['status'] == 'ready' else (
                row['diameter_mm'], row['drill_mm'])
            dc.SetPen(wx.Pen(color, 2))
            dc.SetBrush(wx.Brush('#263747'))
            dc.DrawCircle(x, y, max(3, round(proposed[0]*scale/2)))
            dc.SetPen(wx.Pen('#8C9AAB', 1, wx.PENSTYLE_DOT))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawCircle(x, y, max(2, round(row['diameter_mm']*scale/2)))
            dc.SetPen(wx.Pen(color, 1))
            dc.SetBrush(wx.Brush('#19212D'))
            dc.DrawCircle(x, y, max(1, round(proposed[1]*scale/2)))


class ViaManagerPanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        self.result = None
        self.inventory = []
        self.catalog_ready = False
        outer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label='Filter saved via sizes, select them in PCB Editor, '
                              'or scan larger through vias. Save project settings first.')
        outer.Add(intro, 0, wx.ALL, 9)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.size = wx.Choice(self, choices=['All sizes'])
        self.size.SetSelection(0)
        self.size.SetMinSize((245, -1))
        self.net = wx.Choice(self, choices=['All nets'])
        self.net.SetSelection(0)
        self.net.SetMinSize((190, -1))
        self.selected = wx.CheckBox(self, label='Selected vias only')
        self.size.Bind(wx.EVT_CHOICE, self.invalidate)
        self.net.Bind(wx.EVT_CHOICE, self.invalidate)
        self.selected.Bind(wx.EVT_CHECKBOX, self.invalidate)
        for control in (self.size, self.net, self.selected):
            filters.Add(control, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 9)
        read = wx.Button(self, label='Refresh sizes (F5)')
        read.Bind(wx.EVT_BUTTON, self.on_refresh)
        filters.Add(read)
        outer.Add(filters, 0, wx.ALL, 9)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        select = wx.Button(self, label='Select matching in PCB')
        select.Bind(wx.EVT_BUTTON, self.on_select)
        delete = wx.Button(self, label='Delete matching...')
        delete.Bind(wx.EVT_BUTTON, self.on_delete)
        for button in (select, delete):
            actions.Add(button, 0, wx.RIGHT, 9)
        actions.Add(wx.StaticText(self, label='Grow to diameter / drill (mm):'), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.target = wx.ComboBox(self, choices=[f'{d:.2f} / {h:.2f}' for d, h in PRESETS],
                                  value='0.60 / 0.30', size=(135, -1))
        self.target.Bind(wx.EVT_TEXT, self.invalidate)
        self.target.Bind(wx.EVT_COMBOBOX, self.invalidate)
        actions.Add(self.target, 0, wx.RIGHT, 9)
        scan = wx.Button(self, label='Analyze enlargement')
        scan.Bind(wx.EVT_BUTTON, self.on_scan)
        actions.Add(scan, 0, wx.RIGHT, 9)
        self.apply = wx.Button(self, label='Apply verified vias')
        self.apply.Disable()
        self.apply.Bind(wx.EVT_BUTTON, self.on_apply)
        actions.Add(self.apply)
        outer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.summary = wx.StaticText(self, label='Refresh sizes to inventory the board.')
        outer.Add(self.summary, 0, wx.ALL, 9)
        self.canvas = ViaSizePreview(self)
        outer.Add(self.canvas, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 9)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for col, title, width in ((0, 'State', 80), (1, 'Net', 180), (2, 'Current mm', 110),
                                  (3, 'X / Y mm', 160), (4, 'Reason', 650)):
            self.table.InsertColumn(col, title, width=width)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_focus)
        outer.Add(self.table, 1, wx.EXPAND | wx.ALL, 9)
        self.status = wx.StaticText(self, label='Scan compares new DRC findings with the current '
                                   'board on temporary copies. No source files are saved.')
        outer.Add(self.status, 0, wx.ALL, 9)
        self.SetSizer(outer)

    def message(self, value, state='pending'):
        self.status.SetLabel(value)
        self.status.SetForegroundColour(self.host.colors.get(state, self.host.colors['pending']))
        self.Layout()

    def invalidate(self, event=None):
        self.result = None
        self.apply.Disable()
        self.table.DeleteAllItems()
        self.canvas.show([])
        if event:
            event.Skip()

    def filters(self):
        result = dict(selected_only=self.selected.GetValue())
        index = self.size.GetSelection()
        if index > 0:
            row = self.inventory[index-1]
            result.update(diameter_mm=row['diameter_mm'], drill_mm=row['drill_mm'])
        if self.net.GetSelection() > 0:
            result['net'] = self.net.GetStringSelection()
        return result

    def call(self, operation, done, **payload):
        if not self.native:
            self.message('Open TraceForge from PCB Editor for native access.', 'error')
            return
        self.host.submit_stitching(lambda: self.native(operation, **payload), done, self)

    def on_refresh(self, event=None):
        old_filter = self.filters()
        self.catalog_ready = False
        self.invalidate()

        def done(result):
            if result.get('catalog_version') != 2:
                self.message('PCB Editor is still using an older 0.12.9 helper. Close ALL KiCad '
                             'windows and reopen after reinstalling the updated PCM.', 'error')
                return
            self.inventory = result['sizes']
            self.size.Set(['All sizes'] + [
                f"{r['diameter_mm']:.3f} / {r['drill_mm']:.3f} mm - {r['count']} used"
                + (' [predefined]' if r['sources'] else ' [placed only]')
                for r in self.inventory])
            self.size.SetSelection(0)
            for i, row in enumerate(self.inventory, 1):
                if (row['diameter_mm'] == old_filter.get('diameter_mm') and
                        row['drill_mm'] == old_filter.get('drill_mm')):
                    self.size.SetSelection(i)
            self.net.Set(['All nets'] + result['nets'])
            self.net.SetSelection(0)
            if old_filter.get('net') in result['nets']:
                self.net.SetSelection(result['nets'].index(old_filter['net'])+1)
            target = self.target.GetValue()
            choices = sorted(set(PRESETS) | {
                (row['diameter_mm'], row['drill_mm']) for row in self.inventory})
            self.target.Set([f'{d:.3f} / {h:.3f}' for d, h in choices])
            self.target.ChangeValue(target)
            self.catalog_ready = True
            locked = sum(row['locked'] for row in self.inventory)
            predefined = sum(bool(row['sources']) for row in self.inventory)
            self.summary.SetLabel(f"{result['total']} placed vias | "
                                  f'{predefined} predefined sizes | '
                                  f'{locked} locked (protected from delete and resize)')
            self.message('Predefined sizes include unused presets. Same-diameter edits use '
                         'local hole checks when supported; larger copper uses full DRC.')

        self.call('via_manage_inventory', done)

    def on_select(self, event=None):
        if not self.require_catalog():
            return
        def done(result):
            dim = ('Other connected copper is dimmed.' if result['dimmed'] else
                   'Dimming unavailable or disabled; the selection is still exact. ' +
                   result.get('dim_warning', ''))
            self.message(f"KiCad selected exactly {result['count']} matching vias. "
                         'Right-click them in PCB Editor to edit. ' + dim, 'ok')

        self.call('via_manage_select', done, **self.filters())

    def require_catalog(self):
        if not self.catalog_ready:
            self.message('Click Refresh sizes (F5) first to load and verify live project presets.',
                         'warning')
        return self.catalog_ready

    def show_result(self, result):
        self.result = result
        self.table.DeleteAllItems()
        self.canvas.show(result['vias'], (result['diameter_mm'], result['drill_mm']))
        for row in result['vias']:
            index = self.table.InsertItem(self.table.GetItemCount(), row['status'])
            for col, value in enumerate((row['net'],
                                        f"{row['diameter_mm']:.3f} / {row['drill_mm']:.3f}",
                                        f"{row['x_mm']:.3f} / {row['y_mm']:.3f}",
                                        row['reason']), 1):
                self.table.SetItem(index, col, value)
        ready = len(result['ready'])
        blocked = sum(row['status'] == 'blocked' for row in result['vias'])
        skipped = len(result['vias']) - ready - blocked
        remaining = sum(row['drill_mm'] < result['drill_mm'] and row['uuid'] not in
                        result['ready'] for row in result['vias'])
        self.summary.SetLabel(f'{ready} can grow | {blocked} blocked | {skipped} skipped | '
                              f"{remaining} matching / "
                              f"{result['board_remaining_small']} whole-board "
                              'vias remain below target drill')
        self.apply.Enable(bool(ready))
        if result.get('method') == 'no changes':
            self.message('No eligible vias need this change. No DRC scan was run.')
        elif result.get('method') == 'local hole checks':
            self.message('Drill-only checks completed: copper diameter is unchanged; no full-board '
                         'routing scan or zone refill was needed. Red vias remain unchanged.', 'ok')
        else:
            self.message(f"Full DRC: final batch adds no findings; {result['baseline_findings']} "
                         'baseline findings retained. ' + result.get('fallback_reason', ''), 'ok')

    def on_scan(self, event=None):
        if not self.require_catalog():
            return
        if not self.native:
            self.message('Open TraceForge from PCB Editor.', 'error')
            return
        try:
            diameter, drill = (float(v.strip()) for v in self.target.GetValue().split('/'))
            if not 0 < drill < diameter <= 10:
                raise ValueError()
        except ValueError:
            self.message('Enter target diameter / drill in mm, e.g. 0.60 / 0.30.', 'error')
            return
        self.invalidate()
        filters = self.filters()
        self.message('Checking changed geometry. Same-diameter edits use local hole checks; '
                     'copper enlargement or unsupported rules use full DRC. '
                     'PCB edits invalidate the preview.')

        def work(cancel):
            prepared = self.native('via_manage_prepare', **filters,
                                   target_diameter_mm=diameter, target_drill_mm=drill,
                                   cancel_file=cancel.path)
            return analyze(prepared, cancel=cancel)

        self.host.submit_stitching(work, self.show_result, self, cancellable=True)

    def on_apply(self, event=None):
        if self.result:
            token = self.result['token']
            self.invalidate()
            self.call('via_manage_apply', lambda r: self.message(r['message'], 'ok'), token=token)

    def on_focus(self, event):
        if self.result:
            identity = self.result['vias'][event.GetIndex()]['uuid']
            self.call('via_manage_focus', lambda r: None, ids=[identity])

    def on_delete(self, event=None):
        if not self.require_catalog():
            return
        self.invalidate()

        def prepared(result):
            count = sum(row['status'] == 'candidate' for row in result['vias'])
            if not count:
                self.message('No unlocked matching vias to delete.')
                return
            with wx.MessageDialog(self,
                                  f'Delete {count} unlocked matching vias? This may remove '
                                  'signal or stitching connections. Undo will restore them.',
                                  'Delete matching vias', wx.YES_NO | wx.NO_DEFAULT |
                                  wx.ICON_WARNING) as dialog:
                if dialog.ShowModal() != wx.ID_YES:
                    return
            self.call('via_manage_delete', lambda r: self.message(r['message'], 'ok'),
                      token=result['token'])

        self.call('via_manage_prepare_delete', prepared, **self.filters())
