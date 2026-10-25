"""Explicit RF fence-spacing suggestion using saved laminate data or user epsilon effective."""
import wx

from .rf_guidance import spacing


class RFGuideDialog(wx.Dialog):
    def __init__(self, parent, dielectrics):
        super().__init__(parent, title='RF fence spacing helper', size=(660, 490))
        self.value = None
        box = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label='Use the highest frequency of interest. This estimates '
                              'wavelength-based spacing, not the copper gap or impedance.')
        intro.Wrap(610)
        box.Add(intro, 0, wx.ALL, 10)
        form = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        self.frequency = wx.TextCtrl(self, value='2400')
        self.er = wx.TextCtrl(self, value='4.2')
        self.division = wx.Choice(self, choices=['Wavelength / 20', 'Wavelength / 10'])
        self.division.SetSelection(0)
        self.material = wx.Choice(self, choices=['Manual input (4.2 is an assumed default)'] +
                                  [f"{d['name']}: er {d['epsilon_r']:g}, "
                                   f"{d['thickness_mm']:g} mm" for d in dielectrics])
        self.material.SetSelection(0)
        for label, control in [('Frequency (MHz)', self.frequency),
                               ('Saved board dielectric', self.material),
                               ('Relative / effective permittivity', self.er),
                               ('Spacing criterion', self.division)]:
            form.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        form.AddGrowableCol(1)
        box.Add(form, 0, wx.EXPAND | wx.ALL, 10)
        self.output = wx.StaticText(self)
        box.Add(self.output, 0, wx.EXPAND | wx.ALL, 10)
        note = wx.StaticText(self, label='Saved values come from the last saved board stackup. '
                             'Choose the dielectric relevant to your signal layer. Laminate er '
                             'gives a bulk-dielectric wavelength estimate; enter effective '
                             'permittivity from your field solver for a guided-mode estimate. '
                             'Thickness is shown as context and is not used in this formula.\n\n'
                             'Antenna matching, coplanar geometry and return-plane connectivity '
                             'still require design review. Preview checks physical via clearances. '
                             'This suggestion changes spacing only; the copper gap stays yours.')
        note.Wrap(610)
        box.Add(note, 0, wx.EXPAND | wx.ALL, 10)
        self.use = wx.Button(self, wx.ID_OK, label='Use suggested spacing')
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.use, 0, wx.RIGHT, 8)
        row.Add(wx.Button(self, wx.ID_CANCEL))
        box.Add(row, 0, wx.ALL, 10)
        self.SetSizer(box)
        def material(event):
            index = self.material.GetSelection()
            if index:
                self.er.SetValue(str(dielectrics[index - 1]['epsilon_r']))
        self.material.Bind(wx.EVT_CHOICE, material)
        for control, kind in [(self.frequency, wx.EVT_TEXT), (self.er, wx.EVT_TEXT),
                              (self.division, wx.EVT_CHOICE)]:
            control.Bind(kind, self.calculate)
        self.calculate()

    def calculate(self, event=None):
        try:
            result = spacing(self.frequency.GetValue(), self.er.GetValue(),
                             20 if self.division.GetSelection() == 0 else 10)
            self.value = result['spacing_mm']
            self.output.SetLabel(f"Wavelength: {result['wavelength_mm']:.3f} mm\n"
                                 f"Suggested maximum spacing: {self.value:.3f} mm\n"
                                 'lambda = c / (frequency * sqrt(permittivity))')
            self.use.Enable()
        except (ValueError, OverflowError) as exc:
            self.value = None
            self.output.SetLabel(str(exc))
            self.use.Disable()
        self.Layout()
