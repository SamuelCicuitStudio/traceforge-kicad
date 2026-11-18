"""Components workspace launched independently from a schematic or project."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def project_from_netlist(path):
    source = ET.parse(path).findtext("./design/source")
    if not source:
        raise ValueError("KiCad netlist has no design/source project path")
    source = Path(source).resolve()
    if source.suffix.lower() != ".kicad_sch" or not source.is_file():
        raise ValueError("Netlist source must identify an existing root schematic")
    return source


def main(argv=None):
    parser = argparse.ArgumentParser(description="TraceForge schematic component research/import")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--from-netlist", type=Path)
    parser.add_argument(
        "--launch", action="store_true", help="Launch separately and return to KiCad"
    )
    args = parser.parse_args(argv)
    project = project_from_netlist(args.from_netlist) if args.from_netlist else args.project
    if args.launch:
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "traceforge_components.py"),
        ]
        if project:
            command += ["--project", str(project)]
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return 0
    import wx

    from .components_ui import ComponentsPanel

    class ComponentWindow(wx.Frame):
        def __init__(self):
            super().__init__(None, title="TraceForge / Schematic Components", size=(1240, 840))
            self.dark = True
            self.SetBackgroundColour("#222c3a")
            outer = wx.BoxSizer(wx.VERTICAL)
            bar = wx.BoxSizer(wx.HORIZONTAL)
            label = wx.StaticText(self, label="Schematic project:")
            label.SetForegroundColour("#e5edf8")
            bar.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            self.picker = wx.FilePickerCtrl(
                self,
                path=str(project or ""),
                wildcard="KiCad designs|*.kicad_sch;*.kicad_pro;*.kicad_pcb",
            )
            self.picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.change_project)
            bar.Add(self.picker, 1)
            outer.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
            self.components = ComponentsPanel(self, self, None, str(project or ""))
            outer.Add(self.components, 1, wx.EXPAND)
            self.SetSizer(outer)
            self.Bind(wx.EVT_CLOSE, self.close)

        def change_project(self, event):
            if self.components.working:
                self.components.message(
                    "Finish or cancel the current import before changing project."
                )
                self.picker.SetPath(self.components.board_file)
                return
            self.components.board_file = self.picker.GetPath()
            self.components.load_project()

        def workspace_changed(self):
            self.Layout()

        def on_overlay(self, event=None):
            pass

        def close(self, event):
            self.components.shutdown()
            self.Destroy()

    app = wx.App(False)
    if hasattr(app, "MSWEnableDarkMode"):
        app.MSWEnableDarkMode(1)
    window = ComponentWindow()
    window.Show()
    window.Raise()
    app.MainLoop()
    return 0
