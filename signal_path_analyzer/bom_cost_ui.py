"""Manufacturing retail BOM estimate, with explicit unpriced lines and timestamps."""

from __future__ import annotations

import csv
import json
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

import wx

from . import bom_cost, bom_identity, bom_source
from .component_runtime import Worker
from .lcsc_research_ui import FG, GOLD, GREEN, INPUT, style


class BomCostPanel(wx.Panel):
    def __init__(self, parent, host, native, board_file):
        super().__init__(parent)
        if host.dark:
            self.SetBackgroundColour("#222C3A")
            self.SetForegroundColour("#E5EDF8")
        self.host, self.native, self.board_file = host, native, board_file
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="traceforge-bom")
        self.cancel = threading.Event()
        self.generation = 0
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
        controls.Add(self.boards, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)
        controls.Add(
            wx.StaticText(self, label="Spares %:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5
        )
        self.spares = wx.SpinCtrl(self, min=0, max=100, initial=0, size=(70, -1))
        controls.Add(self.spares, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)
        self.live = wx.CheckBox(self, label="Refresh live LCSC prices")
        controls.Add(self.live, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.calculate = wx.Button(self, label="Calculate BOM cost")
        style(self.calculate, True)
        self.calculate.Bind(wx.EVT_BUTTON, self.on_calculate)
        controls.Add(self.calculate, 0, wx.ALIGN_CENTER_VERTICAL)
        stop = wx.Button(self, label="Cancel")
        stop.Bind(wx.EVT_BUTTON, self.on_cancel)
        controls.Add(stop, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 5)
        optimize = style(wx.Button(self, label="Optimize BOM"), True)
        optimize.Bind(wx.EVT_BUTTON, self.on_optimize)
        action_row = wx.BoxSizer(wx.HORIZONTAL)
        action_row.Add(optimize, 0, wx.RIGHT, 6)
        assembly = style(wx.Button(self, label="JLCPCB assembly check"))
        assembly.Bind(wx.EVT_BUTTON, lambda event: self.on_optimize(event, check_only=True))
        action_row.Add(assembly, 0, wx.RIGHT, 6)
        assign = style(wx.Button(self, label="Assign in-stock passives"), True)
        assign.Bind(wx.EVT_BUTTON, lambda event: self.on_optimize(event, assign_mode=True))
        action_row.Add(assign, 0)
        controls.AddStretchSpacer(1)
        total_box = wx.BoxSizer(wx.VERTICAL)
        self.total_amount = wx.StaticText(self, label="USD --")
        self.total_amount.SetFont(self.total_amount.GetFont().Bold().Larger().Larger().Larger())
        self.total_amount.SetForegroundColour(GREEN)
        self.total_caption = wx.StaticText(self, label="Calculate BOM cost")
        self.total_caption.SetForegroundColour("#a8b4c7")
        total_box.Add(self.total_amount, 0, wx.ALIGN_RIGHT)
        total_box.Add(self.total_caption, 0, wx.ALIGN_RIGHT | wx.TOP, 2)
        controls.Add(total_box, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 16)
        outer.Add(controls, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(action_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        loading = wx.BoxSizer(wx.HORIZONTAL)
        self.loading_activity = wx.ActivityIndicator(self)
        loading.Add(self.loading_activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.loading_label = wx.StaticText(self, label="Ready to calculate")
        self.loading_label.SetForegroundColour(GOLD)
        loading.Add(self.loading_label, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(loading, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        note = wx.StaticText(
            self,
            label="LCSC retail parts, USD. Cached observations retain their dates. "
            "Order includes MOQ/multiples; Leftover = Order - Fitted. "
            "Excludes PCB, assembly, freight and taxes.",
        )
        note.Wrap(900)
        outer.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        legend = wx.BoxSizer(wx.HORIZONTAL)
        for label, colour in (
            ("Ready", "#6ee7a0"),
            ("Unassigned / conflict", "#ff8585"),
            ("Stock short", "#ffd166"),
            ("Price missing", "#c5a3ff"),
            ("Stock unknown", "#9acbff"),
        ):
            item = wx.StaticText(self, label=label)
            item.SetForegroundColour(colour)
            item.SetFont(item.GetFont().Bold())
            legend.Add(item, 0, wx.RIGHT, 18)
        outer.Add(legend, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (name, width) in enumerate(
            [
                ("State", 105),
                ("LCSC code", 95),
                ("MPN", 190),
                ("References", 105),
                ("Fitted", 50),
                ("MOQ", 55),
                ("Multiple", 60),
                ("Order", 55),
                ("Leftover", 65),
                ("USD / item", 80),
                ("USD line", 85),
                ("Retail stock", 85),
                ("Observed UTC", 125),
                ("Status", 170),
                ("JLCPCB class", 125),
                ("Assembly stock", 110),
            ]
        ):
            self.table.InsertColumn(i, name, width=width)
        self.table.SetBackgroundColour(INPUT)
        self.table.SetForegroundColour(FG)
        self.table.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_row_menu)
        self.table.Bind(
            wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self.research_row(event.GetIndex())
        )
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.status = wx.StaticText(
            self, label="Calculate to inspect all priced and unpriced BOM lines."
        )
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        export = wx.Button(self, label="Export cost report (JSON + CSV)")
        export.Bind(wx.EVT_BUTTON, self.on_export)
        outer.Add(export, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(outer)

    def loading(self, text, active=True):
        self.loading_label.SetLabel(text)
        if active:
            self.loading_activity.Start()
        else:
            self.loading_activity.Stop()

    def message(self, text, state="pending"):
        """Board-operation runner feedback, matching the other TraceForge pages."""
        colour = {"error": "#ff8585", "warning": GOLD, "routed": GREEN}.get(state, FG)
        self.status.SetForegroundColour(colour)
        self.status.SetLabel(str(text))
        self.status.Wrap(max(300, self.GetClientSize().width - 20))
        self.Layout()

    def invalidate(self):
        """A failed visual-focus operation does not invalidate the priced BOM."""
        return None

    def on_cancel(self, event=None):
        if not self.working:
            return False
        self.cancel.set()
        self.loading("Cancellation requested", False)
        self.total_amount.SetLabel("USD --")
        self.total_caption.SetLabel("Cancelling...")
        self.total_caption.SetForegroundColour(GOLD)
        self.message("Cancellation requested; supplier results will not be applied.", "warning")
        return True

    def on_calculate(self, event=None):
        if self.working:
            return
        if not self.native and self.source.GetSelection() == 1:
            self.status.SetLabel("Open a saved PCB with the native helper first.")
            return
        boards, spares, refresh = (
            self.boards.GetValue(),
            self.spares.GetValue(),
            self.live.GetValue(),
        )
        source_index = self.source.GetSelection()
        schematic_path = self.schematic.GetPath()
        self.cancel = threading.Event()
        cancel = self.cancel
        self.generation += 1
        generation = self.generation
        self.result = None
        self.working = True
        self.loading("Scanning saved schematic" if source_index == 0 else "Scanning live PCB")
        self.calculate.Disable()
        self.total_amount.SetLabel("USD --")
        self.total_caption.SetLabel("Calculating...")
        self.total_caption.SetForegroundColour("#a8b4c7")
        self.status.SetLabel("Reading live PCB fields and supplier observations...")

        def show_progress(text):
            if not self.closed and generation == self.generation and not cancel.is_set():
                self.status.SetLabel(text)
                self.loading(text)

        def progress(index, count, code):
            if not self.closed and not cancel.is_set():
                wx.CallAfter(show_progress, f"Pricing {index}/{count}: {code or 'missing code'}")

        def finish(result, error):
            if not self.closed and generation == self.generation:
                self.done(result, error)

        def work():
            try:
                if source_index == 0:
                    worker = Worker()
                    worker.cancel = cancel
                    cli = shutil.which("kicad-cli") or str(
                        Path(sys.executable).parent / "kicad-cli.exe"
                    )
                    data = bom_source.saved_schematic(schematic_path, worker, cli)
                else:
                    data = self.host.api.call(lambda: self.native("bom_snapshot"))
                wx.CallAfter(show_progress, "Resolving component supplier identities...")
                parts = bom_identity.resolve(data["parts"], cancel, progress)
                result = bom_cost.estimate(parts, boards, spares, refresh, cancel, progress)
                result["source"] = data["source"]
                result["source_parts"] = data["parts"]
                result["resolved_parts"] = parts
                result["schematic"] = data.get("schematic")
                result["identity_resolution"] = {
                    p["reference"]: p.get("identity_source", "saved supplier field") for p in parts
                }
                error = None
            except Exception as exc:
                result, error = None, exc
            if not self.closed:
                wx.CallAfter(finish, result, error)

        self.executor.submit(work)

    def update_assembly_observations(self, observations):
        if not self.result:
            return
        cached = self.result.setdefault("assembly_observations", {})
        for code, part in observations.items():
            cached[code] = dict(
                tier=part.assembly_tier,
                stock=part.assembly_stock,
                prices=part.assembly_prices,
                observed_at=part.assembly_observed_at,
                source=part.assembly_source,
            )
        for index, row in enumerate(self.result["lines"]):
            observation = cached.get(row["lcsc"], {})
            self.table.SetItem(index, 14, observation.get("tier", "Not checked"))
            stock = observation.get("stock")
            self.table.SetItem(index, 15, "Unknown" if stock is None else f"{stock:,}")

    def on_optimize(self, event=None, check_only=False, assign_mode=False):
        if self.working or not self.result:
            self.message(
                "Calculate the BOM first, then optimize or check assembly stock.", "warning"
            )
            return
        from .bom_optimizer_ui import OptimizerDialog

        dialog = OptimizerDialog(self, check_only, assign_mode=assign_mode)
        dialog.ShowModal()
        dialog.Destroy()

    def refresh_assignment(self, references, properties):
        self.refresh_assignments([(references, properties)])

    def refresh_assignments(self, changes, on_complete=None):
        if self.closed or not self.result:
            return
        previous = self.result
        self.cancel = threading.Event()
        cancel = self.cancel
        self.generation += 1
        generation = self.generation
        self.working = True
        self.calculate.Disable()
        self.status.SetLabel("Updating assigned components and affected totals...")
        self.loading("Updating affected BOM rows and totals")

        def finish(result, error):
            if not self.closed and generation == self.generation:
                if error or cancel.is_set():
                    self.working = False
                    self.loading("BOM refresh stopped", False)
                    self.calculate.Enable()
                    self.message(
                        "Component information saved; BOM refresh: " + str(error or "cancelled"),
                        "warning",
                    )
                    if on_complete:
                        on_complete(error or "Cancelled")
                    return
                self.done(result, None, incremental=True)
                if on_complete:
                    on_complete(None)

        def work():
            try:
                result = previous
                for references, properties in changes:
                    result = bom_cost.update_assignment(result, references, properties, cancel)
                error = None
            except Exception as exc:
                result, error = None, exc
            wx.CallAfter(finish, result, error)

        self.executor.submit(work)

    def done(self, result, error, incremental=False):
        if self.closed:
            return
        self.working = False
        self.loading(
            "Cancelled"
            if self.cancel.is_set()
            else "Calculation failed"
            if error
            else "BOM scan complete",
            False,
        )
        self.calculate.Enable()
        if self.cancel.is_set():
            self.result = None
            self.total_amount.SetLabel("USD --")
            self.total_caption.SetLabel("Cancelled")
            self.total_caption.SetForegroundColour(GOLD)
            self.message("BOM calculation cancelled. No incomplete total was applied.", "warning")
            return
        if error:
            self.total_amount.SetLabel("USD --")
            self.total_caption.SetLabel("Calculation failed")
            self.total_caption.SetForegroundColour("#ff8585")
            self.status.SetLabel(str(error))
            return
        previous_rows = self.result["lines"] if incremental and self.result else []
        self.result = result
        amount = Decimal(result["known_parts_subtotal_usd"])
        self.total_amount.SetLabel(f"USD {amount:,.2f}")
        self.total_amount.SetForegroundColour(GREEN)
        self.total_amount.SetToolTip("Exact parts subtotal: USD " + str(amount))
        incomplete = result["unpriced_lines"]
        self.total_caption.SetLabel(
            f"Subtotal | {incomplete} unpriced lines" if incomplete else "Complete parts total"
        )
        self.total_caption.SetForegroundColour(GOLD if incomplete else GREEN)
        self.Layout()
        selected = self.table.GetFirstSelected()
        selected_refs = (
            set(previous_rows[selected]["references"])
            if 0 <= selected < len(previous_rows)
            else set()
        )
        top = self.table.GetTopItem()
        if incremental:
            old_keys = [tuple(row["references"]) for row in previous_rows]
            new_keys = [tuple(row["references"]) for row in result["lines"]]
            for tag, a, b, c, d in reversed(
                SequenceMatcher(None, old_keys, new_keys).get_opcodes()
            ):
                if tag != "equal":
                    for i in range(b - 1, a - 1, -1):
                        self.table.DeleteItem(i)
                    for i in range(d - c):
                        self.table.InsertItem(a + i, "")
        else:
            self.table.DeleteAllItems()
        for index, row in enumerate(result["lines"]):
            if incremental and index < len(previous_rows) and previous_rows[index] == row:
                continue
            state = bom_cost.availability_state(row)
            colours = {
                "Ready": (FG, "#1c3529"),
                "Unassigned": ("#ff8585", "#3b2831"),
                "Identity conflict": ("#ff8585", "#3b2831"),
                "Stock short": ("#ffd166", "#3b3020"),
                "Price missing": ("#c5a3ff", "#302a40"),
                "Stock unknown": ("#9acbff", "#233145"),
            }
            if incremental:
                i = index
                self.table.SetItem(i, 0, state)
            else:
                i = self.table.InsertItem(self.table.GetItemCount(), state)
            foreground, background = colours[state]
            self.table.SetItemTextColour(i, foreground)
            self.table.SetItemBackgroundColour(i, background)
            values = [
                row["lcsc"],
                row["mpn"],
                ", ".join(row["references"]),
                row["fitted_quantity"],
                row.get("minimum_order") if row.get("minimum_order") is not None else "Unknown",
                row.get("order_multiple") if row.get("order_multiple") is not None else "Unknown",
                row["order_quantity"] if row.get("leftover_quantity") is not None else "Unknown",
                row.get("leftover_quantity")
                if row.get("leftover_quantity") is not None
                else "Unknown",
                row["unit_price_usd"] or "Unknown",
                row["extended_usd"] or "Unknown",
                "Unknown" if row["stock"] is None else row["stock"],
                row["observed_at"] or "",
                row["status"]
                + ("; " + row.get("identity_source", "") if not row["lcsc"] else "")
                + ("; stock shortage" if row.get("stock_shortage") else "")
                + ("; " + row["cache_status"] if row["cache_status"] else ""),
            ]
            for col, value in enumerate(values, 1):
                self.table.SetItem(i, col, str(value))
        self.update_assembly_observations({})
        if incremental:
            for index, row in enumerate(result["lines"]):
                self.table.Select(index, bool(selected_refs.intersection(row["references"])))
            if self.table.GetItemCount() and top >= 0:
                current = self.table.GetTopItem()
                height = self.table.GetItemRect(0).height
                self.table.ScrollList(
                    0, (min(top, self.table.GetItemCount() - 1) - current) * height
                )
        label = (
            "Complete parts estimate"
            if result["complete_parts_total_usd"] is not None
            else "Known-price subtotal (incomplete BOM)"
        )
        self.status.SetForegroundColour(
            GREEN if result["complete_parts_total_usd"] is not None else GOLD
        )
        self.status.SetLabel(
            f"{result['source']}: {label}: USD {result['known_parts_subtotal_usd']}; "
            f"{result['unpriced_lines']} unpriced lines; "
            f"{len(result['excluded_references'])} DNP/excluded references."
        )

    def on_row_menu(self, event):
        index = event.GetIndex()
        if self.working or not self.result or index < 0:
            return
        self.table.Select(index)
        menu = wx.Menu()
        for label, action in [
            ("Research MPN / set LCSC information...", lambda e: self.research_row(index)),
            (
                "Research replacement using current specifications...",
                lambda e: self.research_row(index, replacement=True),
            ),
            ("Highlight and zoom in PCB", lambda e: self.select_in_pcb(index)),
        ]:
            item = menu.Append(wx.ID_ANY, label)
            if label.startswith("Highlight"):
                item.Enable(self.native is not None)
            menu.Bind(wx.EVT_MENU, action, id=item.GetId())
        self.PopupMenu(menu)
        menu.Destroy()

    def research_row(self, index, replacement=False):
        if not self.result or not 0 <= index < len(self.result["lines"]):
            return
        self.host.components.begin_bom_assignment(self, self.result["lines"][index], replacement)

    def select_in_pcb(self, index):
        if not self.native or not self.result:
            return
        refs = self.result["lines"][index]["references"]

        def done(result):
            message = "Highlighted in PCB: " + ", ".join(result["selected"])
            self.status.SetLabel(
                message
                + (
                    "; zoomed to component."
                    if result.get("zoomed")
                    else "; native zoom is unavailable in this editor window."
                )
            )

        def focus():
            info = self.native("info")
            if self.board_file and Path(info["board"]).resolve() != Path(self.board_file).resolve():
                raise ValueError("Active PCB changed; recalculate the BOM")
            root = self.result.get("schematic")
            if root and Path(info["board"]).resolve().parent != Path(root).resolve().parent:
                raise ValueError("BOM belongs to another project")
            # Use the same mature path as Signals. Do not gate transient highlights
            # on GetCurrentSelection(), which is a different KiCad selection container.
            highlighted = self.native("highlight", nets=[], refs=refs, zoom=True)
            if highlighted != len(set(refs)):
                self.native("clear")
                raise ValueError(
                    "Some BOM references are missing from the active PCB; synchronize it first"
                )
            zoomed = bool(self.native("zoom"))
            return dict(selected=refs, highlighted=highlighted, zoomed=zoomed)

        self.host.submit_stitching(focus, done, self)

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
            "minimum_order",
            "order_multiple",
            "requested_spares",
            "order_quantity",
            "leftover_quantity",
            "moq_extra_quantity",
            "unit_price_usd",
            "extended_usd",
            "stock",
            "observed_at",
            "status",
            "assembly_tier",
            "assembly_stock",
            "assembly_observed_at",
        ]
        with path.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in self.result["lines"]:
                assembly = self.result.get("assembly_observations", {}).get(row["lcsc"], {})
                writer.writerow(
                    dict(
                        row,
                        references=", ".join(row["references"]),
                        assembly_tier=assembly.get("tier", "Not checked"),
                        assembly_stock=assembly.get("stock"),
                        assembly_observed_at=assembly.get("observed_at", ""),
                    )
                )
        self.status.SetLabel("Exported JSON evidence and CSV cost lines.")

    def shutdown(self):
        self.closed = True
        self.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
