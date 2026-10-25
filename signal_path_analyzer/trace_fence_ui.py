"""Dedicated RF trace-following fencing tab, sharing validated via lifecycle operations."""
from __future__ import annotations

import wx

from .stitching import settings
from .stitching_ui import StitchingPanel


class TraceFencePanel(StitchingPanel):
    def __init__(self, parent, host, native):
        def fence_native(operation, **payload):
            return native(operation.replace('stitch_', 'tracefence_', 1), **payload)

        super().__init__(parent, host, fence_native if native else None, trace_mode=True)
        self.region_label.SetLabel('No source path. Select RF track segments in PCB Editor.')
        self.sets.SetColumnWidth(0, 230)
        column = self.sets.GetColumn(0)
        column.SetText('Trace fence set')
        self.sets.SetColumn(0, column)
        helper = wx.Button(self, label='RF spacing helper...')
        helper.Bind(wx.EVT_BUTTON, self.on_rf_helper)
        self.GetSizer().Insert(1, helper, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.fields['trace_gap'].SetToolTip(
            'Edge-to-edge gap from signal copper to via annulus, not centerline offset. '
            'Centerline offset = gap + half trace width + half via diameter.')
        pick = wx.Button(self, label='Pick fence net in PCB...')
        pick.Bind(wx.EVT_BUTTON, self.on_pick_net)
        self.GetSizer().Insert(1, pick, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.net.SetToolTip('Type an existing fence net name, select the list, or Pick fence net '
                            'in PCB. This is the via net (normally GND), not the RF signal net.')
        source = wx.BoxSizer(wx.HORIZONTAL)
        source.Add(wx.StaticText(self, label='Signal net to fence:'), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.signal_net = wx.ComboBox(self, style=wx.CB_DROPDOWN, size=(240, -1))
        self.signal_net.Bind(wx.EVT_TEXT, self.invalidate)
        source.Add(self.signal_net, 0, wx.RIGHT, 6)
        for label, handler in [('Use signal net', self.on_signal_net),
                               ('Pick signal net in PCB...', self.on_pick_signal)]:
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            source.Add(button, 0, wx.RIGHT, 6)
        self.GetSizer().Insert(1, source, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

    def on_signal_net(self, event=None):
        name = self.signal_net.GetValue().strip()
        if not name:
            self.message('Type the signal net name or click Pick signal net in PCB.', 'warning')
            return
        self.task(lambda: self.native('stitch_net_path', net=name), self.accept_signal)

    def accept_signal(self, region):
        self.set_region(region)
        self.signal_net.SetValue(region['net'])
        self.message(f"Signal path detected: {region['net']}. Set the fence net, then Preview.",
                     'ok')

    def on_pick_signal(self, event):
        def work():
            item = self.native('pick_item', mode='net',
                               prompt='TraceForge: click the SIGNAL net to fence. Esc cancels.')
            return self.native('stitch_net_path', net=item['net'])
        self.task(work, self.accept_signal)

    def on_pick_net(self, event):
        def work():
            # Picking is a helper operation, not a trace-fence operation.
            return self.native('pick_item', mode='net',
                               prompt='TraceForge: click a pad/via/track on the FENCE net. '
                                      'Esc cancels.')
        def done(item):
            self.net.SetValue(item['net'])
            self.update_sizes()
            self.invalidate()
            self.message(f"Fence net selected: {item['net']}. Preview before applying.", 'ok')
        self.message('Click a pad/via/track on the fence net in PCB Editor. Esc cancels.', 'routed')
        self.task(work, done)

    def on_rf_helper(self, event):
        def show(dielectrics):
            from .rf_guidance_ui import RFGuideDialog

            with RFGuideDialog(self, dielectrics) as dialog:
                if dialog.ShowModal() == wx.ID_OK and dialog.value is not None:
                    self.fields['pitch_x'].SetValue(f'{dialog.value:.6g}')
                    self.message('RF spacing copied. Preview to validate physical clearances. '
                                 'Copper gap was not changed.', 'routed')
        self.task(lambda: self.native('stitch_stackup'), show)

    def update_pattern(self):
        for key in ('pitch_y', 'offset_x', 'offset_y'):
            self.fields[key].Enable(False)
        self.fields['pitch_x'].SetToolTip('Maximum spacing along each offset trace path.')

    def collect(self):
        if self.region.get('kind') != 'trace':
            raise ValueError('Select an RF track path in PCB Editor, then Use selected trace.')
        if self.signal_net.GetValue().strip() not in ('', self.region['net']):
            raise ValueError('Click Use signal net to load the typed signal before previewing.')
        values = {key: control.GetValue() for key, control in self.fields.items()}
        values.update(pitch_y=values['pitch_x'], offset_x='0', offset_y='0')
        return settings(dict(values, net=self.net.GetValue(), size_source=self.size_source(),
                             pattern='trace', side=('both', 'left', 'right')[
                                 self.pattern.GetSelection()],
                             connection='all' if self.connection.GetSelection() else 'two'))

    def set_region(self, region):
        self.region = region
        self.canvas.region = region if region.get('kind') == 'trace' else None
        if region.get('kind') == 'trace':
            if hasattr(self, 'signal_net'):
                self.signal_net.SetValue(region['net'])
            self.region_label.SetLabel(f"Signal path: {region['net']} on {region['layer']} — "
                                       f"{len(region['tracks'])} segments/arcs")
        else:
            self.region_label.SetLabel('No source path. Use selected trace to capture it.')
        self.invalidate()

    def fill(self, saved):
        super().fill(dict(saved, name=saved.get('name', 'RF trace fence')))
        side = saved.get('settings', {}).get('side', 'both')
        self.pattern.SetSelection({'both': 0, 'left': 1, 'right': 2}.get(side, 0))
        self.update_pattern()

    def accept_scene(self, scene):
        super().accept_scene(scene)
        previous = self.signal_net.GetValue()
        self.signal_net.Set(sorted(scene['nets']))
        self.signal_net.SetValue(previous)
        if self.region.get('kind') != 'trace' and scene.get('selected_trace'):
            self.set_region(scene['selected_trace'])
        self.message('Choose the fence net (normally GND), path side, spacing and copper gap. '
                     'Use selected trace to capture a different signal path.')

    def on_selected(self, event=None):
        def accept(scene):
            self.accept_scene(scene)
            if scene.get('selected_trace'):
                self.set_region(scene['selected_trace'])
            else:
                self.set_region(dict(kind='board'))
                self.message(scene.get('trace_error') or 'Select one connected RF trace path.',
                             'warning')
        self.task(lambda: self.native('stitch_scene'), accept)

    def accept_preview(self, result):
        super().accept_preview(result)
        if result['reasons'].get('insufficient copper contact'):
            self.message(self.status.GetLabel() + ' Some sites lack solid fence-net copper '
                         'on two layers. Check pours, offset and copper-fill setback.', 'warning')
