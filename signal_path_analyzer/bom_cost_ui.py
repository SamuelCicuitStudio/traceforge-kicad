"""Manufacturing retail BOM estimate, with explicit unpriced lines and timestamps."""

from __future__ import annotations

import csv
import json
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import wx

from . import bom_cost, bom_source
from .component_runtime import Worker


class BomCostPanel(wx.Panel):
    def __init__(self, parent, host, native, board_file):
        super().__init__(parent)
        if host.dark:
            self.SetBackgroundColour("#222C3A")
            self.SetForegroundColour("#E5EDF8")
        self.host, self.native, self.board_file = host, native, board_file
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="traceforge-bom")
        self.cancel = threading.Event()
        self.result = None
        self.closed = False
        self.working = False
        outer = wx.BoxSizer(wx.VERTICAL)
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        self.source = wx.Choice(
            self, choices=["Saved root schematic - full BOM", "Live PCB - placed footprints only"]
        )
        schematic = Path(board_file).with_suffix(".kicad_sch") if board_file else None
        self.source.SetSelection(0 if schematic and schematic.is_file() else 1)
        source_row.Add(self.source, 0, wx.RIGHT, 8)
        self.schematic = wx.FilePickerCtrl(
            self,
            path=str(schematic) if schematic else "",
            wildcard="KiCad schematic (*.kicad_sch)|*.kicad_sch",
        )
        source_row.Add(self.schematic, 1)
        outer.Add(source_row, 0, wx.EXPAND | wx.ALL, 8)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(
            wx.StaticText(self, label="Boards:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5
        )
        self.boards = wx.SpinCtrl(self, min=1, max=100000, initial=1, size=(90, -1))
        controls.Add(self.boards, 0, wx.RIGHT, 12)
        controls.Add(
            wx.StaticText(self, label="Spares %:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5
        )
        self.spares = wx.SpinCtrl(self, min=0, max=100, initial=0, size=(70, -1))
        controls.Add(self.spares, 0, wx.RIGHT, 12)
        self.live = wx.CheckBox(self, label="Refresh live LCSC prices")
        controls.Add(self.live, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.calculate = wx.Button(self, label="Calculate BOM cost")
        self.calculate.Bind(wx.EVT_BUTTON, self.on_calculate)
        controls.Add(self.calculate)
        stop = wx.Button(self, label="Cancel")
        stop.Bind(wx.EVT_BUTTON, lambda event: self.cancel.set())
        controls.Add(stop, 0, wx.LEFT, 5)
        outer.Add(controls, 0, wx.EXPAND | wx.ALL, 8)
        note = wx.StaticText(
            self,
            label="LCSC retail parts, USD. Cached observations retain their dates. "
            "Not JLCPCB assembly stock. Excludes PCB, assembly, freight, taxes and fees.",
        )
        note.Wrap(900)
        outer.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (name, width) in enumerate(
            [
                ("LCSC / MPN", 240),
                ("References", 180),
                ("Fitted", 65),
                ("Order", 65),
                ("USD / item", 95),
                ("USD line", 95),
                ("Retail stock", 90),
                ("Observed UTC", 175),
                ("Status", 310),
            ]
        ):
            self.table.InsertColumn(i, name, width=width)
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.status = wx.StaticText(
            self, label="Calculate to inspect all priced and unpriced BOM lines."
        )
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        export = wx.Button(self, label="Export cost report (JSON + CSV)")
        export.Bind(wx.EVT_BUTTON, self.on_export)
        outer.Add(export, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(outer)

    def on_calculate(self, event=None):
        if self.working:
            return
        if not self.native:
            self.status.SetLabel("Open a saved PCB with the native helper first.")
            return
        boards, spares, refresh = (
            self.boards.GetValue(),
            self.spares.GetValue(),
            self.live.GetValue(),
        )
        source_index = self.source.GetSelection()
        schematic_path = self.schematic.GetPath()
        self.cancel.clear()
        self.result = None
        self.working = True
        self.calculate.Disable()
        self.status.SetLabel("Reading live PCB fields and supplier observations...")

        def progress(index, count, code):
            if not self.closed:
                wx.CallAfter(
                    self.status.SetLabel, f"Pricing {index}/{count}: {code or 'missing code'}"
                )

        def work():
            try:
                if source_index == 0:
                    worker = Worker()
                    worker.cancel = self.cancel
                    cli = shutil.which("kicad-cli") or str(
                        Path(sys.executable).parent / "kicad-cli.exe"
                    )
                    data = bom_source.saved_schematic(schematic_path, worker, cli)
                else:
                    data = self.host.api.call(lambda: self.native("bom_snapshot"))
                result = bom_cost.estimate(
                    data["parts"], boards, spares, refresh, self.cancel, progress
                )
                result["source"] = data["source"]
                error = None
            except Exception as exc:
                result, error = None, exc
            if not self.closed:
                wx.CallAfter(self.done, result, error)

        self.executor.submit(work)

    def done(self, result, error):
        if self.closed:
            return
        self.working = False
        self.calculate.Enable()
        if error:
            self.status.SetLabel(str(error))
            return
        self.result = result
        self.table.DeleteAllItems()
        for row in result["lines"]:
            i = self.table.InsertItem(self.table.GetItemCount(), row["lcsc"] + " / " + row["mpn"])
            values = [
                ", ".join(row["references"]),
                row["fitted_quantity"],
                row["order_quantity"],
                row["unit_price_usd"] or "Unknown",
                row["extended_usd"] or "Unknown",
                "Unknown" if row["stock"] is None else row["stock"],
                row["observed_at"] or "",
                row["status"]
                + ("; stock shortage" if row.get("stock_shortage") else "")
                + ("; " + row["cache_status"] if row["cache_status"] else ""),
            ]
            for col, value in enumerate(values, 1):
                self.table.SetItem(i, col, str(value))
        label = (
            "Complete parts estimate"
            if result["complete_parts_total_usd"] is not None
            else "Known-price subtotal (incomplete BOM)"
        )
        self.status.SetLabel(
            f"{result['source']}: {label}: USD {result['known_parts_subtotal_usd']}; "
            f"{result['unpriced_lines']} unpriced lines; "
            f"{len(result['excluded_references'])} DNP/excluded references."
        )

    def on_export(self, event):
        if not self.result:
            self.status.SetLabel("Calculate a cost report before exporting.")
            return
        with wx.FileDialog(
            self,
            "Export BOM cost",
            wildcard="JSON report (*.json)|*.json",
            defaultFile="bom-cost.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        path.write_text(json.dumps(self.result, indent=2) + "\n", encoding="utf-8")
        fields = [
            "lcsc",
            "mpn",
            "references",
            "per_board",
            "fitted_quantity",
            "order_quantity",
            "unit_price_usd",
            "extended_usd",
            "stock",
            "observed_at",
            "status",
        ]
        with path.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in self.result["lines"]:
                writer.writerow(dict(row, references=", ".join(row["references"])))
        self.status.SetLabel("Exported JSON evidence and CSV cost lines.")

    def shutdown(self):
        self.closed = True
        self.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
