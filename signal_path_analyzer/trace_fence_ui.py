"""Dedicated RF trace-following fencing tab, sharing validated via lifecycle operations."""
from __future__ import annotations

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

    def update_pattern(self):
        for key in ('pitch_y', 'offset_x', 'offset_y'):
            self.fields[key].Enable(False)
        self.fields['pitch_x'].SetToolTip('Maximum spacing along each offset trace path.')

    def collect(self):
        if self.region.get('kind') != 'trace':
            raise ValueError('Select an RF track path in PCB Editor, then Use selected trace.')
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
