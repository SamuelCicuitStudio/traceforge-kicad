"""Public About page with an optional, copyable installation diagnostic view."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import wx
import wx.adv

from . import __version__


class AboutPanel(wx.ScrolledWindow):
    def __init__(self, parent, dark, native_info=None):
        super().__init__(parent)
        self.SetScrollRate(0, 12)
        bg = '#222C3A' if dark else '#FFFFFF'
        card_bg = '#19212D' if dark else '#F2F6FB'
        text = '#E5EDF8' if dark else '#1C2735'
        muted = '#A8B4C7' if dark else '#536579'
        accent = '#7DCFFF' if dark else '#145FA0'
        self.SetBackgroundColour(bg)

        def label(value, color=text, scale=1, bold=False):
            control = wx.StaticText(self, label=value)
            control.SetForegroundColour(color)
            if scale != 1 or bold:
                font = control.GetFont()
                if scale != 1:
                    font.Scale(scale)
                if bold:
                    font.MakeBold()
                control.SetFont(font)
            return control

        outer = wx.BoxSizer(wx.VERTICAL)
        hero = wx.Panel(self)
        hero.SetBackgroundColour(card_bg)
        hero_row = wx.BoxSizer(wx.HORIZONTAL)
        icon = Path(__file__).resolve().parents[1] / 'icons' / (
            'traceforge-dark-48.png' if dark else 'traceforge-light-48.png')
        hero_row.Add(wx.StaticBitmap(hero, bitmap=wx.Bitmap(str(icon))),
                     0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        identity = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(hero, label='TraceForge')
        title.SetForegroundColour(text)
        title.SetFont(title.GetFont().Scale(1.7).Bold())
        identity.Add(title, 0, wx.BOTTOM, 3)
        subtitle = wx.StaticText(hero, label='PCB workflow tools for KiCad')
        subtitle.SetForegroundColour(muted)
        identity.Add(subtitle)
        hero_row.Add(identity, 1, wx.ALIGN_CENTER_VERTICAL)
        version = wx.StaticText(hero, label=f'Version {__version__}')
        version.SetForegroundColour(accent)
        version.SetFont(version.GetFont().Bold())
        hero_row.Add(version, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 14)
        hero_layout = wx.BoxSizer(wx.VERTICAL)
        hero_layout.Add(hero_row, 0, wx.EXPAND | wx.ALL, 14)
        hero.SetSizer(hero_layout)
        outer.Add(hero, 0, wx.EXPAND | wx.BOTTOM, 17)

        outer.Add(label('Design, inspect, and clean up PCB routing in one panel.',
                        scale=1.15, bold=True), 0, wx.BOTTOM, 5)
        outer.Add(label('Works with the open board through KiCad 10 native pcbnew access.',
                        color=muted), 0, wx.BOTTOM, 17)

        outer.Add(label('Included tools', bold=True, scale=1.1), 0, wx.BOTTOM, 9)
        features = (
            ('Signals / xSignals', 'Inspect signal paths, timing, and differential pairs.'),
            ('Via Tools', 'Switch between stitching, RF fencing, and existing-via arrays.'),
            ('BGA Fanout', 'Preview and apply guided BGA escape routes.'),
            ('Trace Tools', 'Clean up copper, apply teardrops, or round and restore corners.'),
            ('Visualization', 'Color net groups and control ratsnest visibility.'),
        )
        for name, description in features:
            row = wx.BoxSizer(wx.HORIZONTAL)
            feature_name = label(name, color=accent, bold=True)
            feature_name.SetMinSize((150, -1))
            row.Add(feature_name, 0, wx.RIGHT, 10)
            row.Add(label(description), 1)
            outer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 7)

        outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 12)
        outer.Add(label('KiCad 10  •  Windows  •  MIT License  •  Samuel Circuit Studio',
                        color=muted), 0, wx.BOTTOM, 12)
        links = wx.BoxSizer(wx.HORIZONTAL)
        homepage = 'https://github.com/SamuelCicuitStudio/traceforge-kicad'
        for caption, url in (
            ('Project', homepage),
            ('Documentation', homepage + '#readme'),
            ('Report an issue', homepage + '/issues'),
        ):
            link = wx.adv.HyperlinkCtrl(self, label=caption, url=url)
            link.SetNormalColour(wx.Colour(accent))
            link.SetVisitedColour(wx.Colour(accent))
            links.Add(link, 0, wx.RIGHT, 22)
        outer.Add(links, 0, wx.BOTTOM, 17)

        native_info = native_info or {}
        log_path = Path(os.environ.get('APPDATA', Path.home())) / 'TraceForge' / 'traceforge.log'
        self.diagnostic_text = (
            f'TraceForge panel: {__version__}\n'
            f'PCB Editor helper: {native_info.get("traceforge_version", "unavailable")}\n'
            'Board access: native pcbnew\n'
            f'Panel code: {Path(__file__).resolve().parent / "hub_ui.py"}\n'
            f'Helper code: {native_info.get("helper_path", "unavailable")}\n'
            f'Python: {sys.version.split()[0]}\n'
            f'Log: {log_path}'
        )
        self.diagnostics_button = wx.Button(self, label='Show diagnostics')
        self.diagnostics_button.Bind(wx.EVT_BUTTON, self.toggle_diagnostics)
        outer.Add(self.diagnostics_button, 0, wx.BOTTOM, 8)
        self.diagnostics = wx.Panel(self)
        diagnostic_layout = wx.BoxSizer(wx.VERTICAL)
        self.diagnostic_box = wx.TextCtrl(
            self.diagnostics, value=self.diagnostic_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 142))
        diagnostic_layout.Add(self.diagnostic_box, 0, wx.EXPAND | wx.BOTTOM, 7)
        copy_button = wx.Button(self.diagnostics, label='Copy diagnostics')
        copy_button.Bind(wx.EVT_BUTTON, self.copy_diagnostics)
        diagnostic_layout.Add(copy_button)
        self.diagnostics.SetSizer(diagnostic_layout)
        outer.Add(self.diagnostics, 0, wx.EXPAND)
        self.diagnostics.Hide()

        content = wx.BoxSizer(wx.VERTICAL)
        content.Add(outer, 0, wx.EXPAND | wx.ALL, 20)
        self.SetSizer(content)
        self.Layout()

    def toggle_diagnostics(self, _event=None):
        show = not self.diagnostics.IsShown()
        self.diagnostics.Show(show)
        self.diagnostics_button.SetLabel('Hide diagnostics' if show else 'Show diagnostics')
        self.Layout()
        self.FitInside()

    def copy_diagnostics(self, _event=None):
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self.diagnostic_text))
            finally:
                wx.TheClipboard.Close()
