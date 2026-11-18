"""Owned BOM optimization dialog: explicit criteria, proposals and scoped application."""

from __future__ import annotations

import copy
import math
import threading
from concurrent.futures import ThreadPoolExecutor

import wx

from . import bom_optimizer as optimizer
from .bom_part_research_ui import BomAssignmentSession
from .lcsc_research_ui import FG, GOLD, GREEN, INPUT, button, style


class OptimizerDialog(wx.Dialog):
    def __init__(self, report, check_only=False, assign_mode=False):
        super().__init__(
            report,
            title=(
                "Assign in-stock passives"
                if assign_mode
                else "JLCPCB assembly check"
                if check_only
                else "Optimize BOM / JLCPCB Basic"
            ),
            size=(1180, 680),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        style(self)
        self.report = report
        self.check_only = check_only
        self.assign_mode = assign_mode
        self.apply_total = 0
        self.snapshot = copy.deepcopy(report.result)
        self.parameters = optimizer.Parameters()
        self.backend = report.host.components.catalog_panel.backend
        self.cancel = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bom-optimize")
        self.closed = self.busy = self.applying = False
        self.session = None
        self.proposals = []
        self.changes = []
        outer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(
            self,
            label=(
                "Assign in-stock R/C equivalents; prefer Basic | "
                if assign_mode
                else "Assembly inventory and Basic alternatives | "
            )
            + "existing value and footprint stay fixed",
        )
        title.SetFont(title.GetFont().Bold().Larger())
        title.SetForegroundColour(GREEN)
        outer.Add(title, 0, wx.ALL, 10)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(
            wx.StaticText(self, label="Passives:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5
        )
        self.scope = wx.Choice(self, choices=["Both", "Resistor", "Capacitor"])
        self.scope.SetSelection(0)
        controls.Add(self.scope, 0, wx.RIGHT, 14)
        controls.Add(
            wx.StaticText(self, label="Maximum tolerance:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        self.tolerance = wx.Choice(
            self, choices=["Same or tighter", "0.1%", "1%", "2%", "5%", "10%", "20%"]
        )
        self.tolerance.SetSelection(0)
        controls.Add(self.tolerance, 0, wx.RIGHT, 14)
        self.stock = wx.CheckBox(self, label="Enough assembly stock")
        self.stock.SetValue(True)
        controls.Add(self.stock, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        self.dielectric = wx.CheckBox(self, label="Keep capacitor dielectric")
        self.dielectric.SetValue(True)
        controls.Add(self.dielectric, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(controls, 0, wx.EXPAND | wx.ALL, 10)
        note = wx.StaticText(
            self,
            label="Resistor power and capacitor voltage: same or higher. "
            "Unknown required specifications block a proposal. "
            "Costs below are JLCPCB component estimates; "
            "assembly setup, handling and other fees are excluded.",
        )
        note.Wrap(1100)
        note.SetForegroundColour(GOLD)
        outer.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.table.EnableCheckBoxes(True)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.show_reason)
        self.table.SetBackgroundColour(INPUT)
        self.table.SetForegroundColour(FG)
        for index, (label, width) in enumerate(
            [
                ("References", 110),
                ("Current C-number", 105),
                ("JLCPCB class", 105),
                ("Assembly stock", 95),
                ("Equivalent / MPN" if assign_mode else "Proposed Basic / MPN", 190),
                ("Current USD", 80),
                ("Proposed USD", 80),
                ("Difference USD", 90),
                ("Checks / reason", 260),
            ]
        ):
            self.table.InsertColumn(index, label, width=width)
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.progress_area = wx.Panel(self)
        progress_box = wx.BoxSizer(wx.VERTICAL)
        progress_head = wx.BoxSizer(wx.HORIZONTAL)
        self.activity = wx.ActivityIndicator(self.progress_area)
        progress_head.Add(self.activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.progress_title = wx.StaticText(self.progress_area, label="")
        self.progress_title.SetFont(self.progress_title.GetFont().Bold().Larger())
        self.progress_title.SetForegroundColour(GREEN)
        progress_head.Add(self.progress_title, 1, wx.ALIGN_CENTER_VERTICAL)
        progress_box.Add(progress_head, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.phase = wx.StaticText(self.progress_area, label="")
        self.phase.SetForegroundColour(FG)
        progress_box.Add(self.phase, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.progress_bar = wx.Gauge(self.progress_area, range=100)
        progress_box.Add(self.progress_bar, 0, wx.EXPAND)
        self.progress_area.SetSizer(progress_box)
        outer.Add(self.progress_area, 0, wx.EXPAND | wx.ALL, 10)
        self.progress_area.Hide()
        self.status = wx.StaticText(
            self, label="Click Scan. No component changes are made during analysis."
        )
        self.status.SetForegroundColour(FG)
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 10)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.scan_button = button(
            self,
            "Find in-stock equivalents"
            if assign_mode
            else "Check assembly"
            if check_only
            else "Scan Basic alternatives",
            self.scan,
            True,
        )
        actions.Add(self.scan_button, 0, wx.RIGHT, 6)
        self.apply_button = button(
            self,
            "Assign checked equivalents" if assign_mode else "Apply checked replacements",
            self.apply,
            True,
        )
        self.apply_button.Enable(False)
        self.apply_button.Show(not check_only)
        actions.Add(self.apply_button)
        actions.AddStretchSpacer(1)
        self.cancel_button = button(self, "Cancel operation", self.on_cancel)
        actions.Add(self.cancel_button, 0, wx.RIGHT, 6)
        self.close_button = button(self, "Close", self.on_close)
        actions.Add(self.close_button)
        outer.Add(actions, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(outer)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.CentreOnParent()
        for control in (self.scope, self.tolerance, self.stock, self.dielectric):
            style(control)
            control.Enable(not check_only)
        if assign_mode:
            self.stock.Disable()
            wx.CallAfter(self.scan)

    def loading(self, title, phase="", completed=0, total=100):
        self.progress_area.Show()
        self.progress_title.SetLabel(title)
        self.phase.SetLabel(phase)
        self.progress_bar.SetRange(max(1, total))
        self.progress_bar.SetValue(min(completed, max(1, total)))
        self.activity.Start()
        self.Layout()

    def assignment_progress(self, phase):
        if not self.closed:
            self.phase.SetLabel(phase)
            self.Layout()

    def show_reason(self, event):
        index = event.GetIndex()
        if self.applying:
            return
        if 0 <= index < len(self.proposals):
            self.status.SetLabel(self.proposals[index]["reason"])
            self.status.Wrap(max(300, self.GetClientSize().width - 20))
            self.Layout()

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_cancel()
        else:
            event.Skip()

    def scan(self, event=None):
        if self.busy or self.applying:
            return
        self.cancel = threading.Event()
        cancel = self.cancel
        self.busy = True
        self.scan_button.Disable()
        self.apply_button.Disable()
        self.table.DeleteAllItems()
        params = optimizer.Parameters(
            self.scope.GetStringSelection(),
            self.tolerance.GetStringSelection(),
            self.stock.GetValue(),
            self.dielectric.GetValue(),
            library_tier="all" if self.assign_mode else "basic",
        )

        self.parameters = params
        self.loading(
            "Finding in-stock equivalents" if self.assign_mode else "Checking BOM components"
        )

        def progress(index, count, refs):
            def show():
                if not self.closed and not cancel.is_set():
                    self.status.SetLabel(f"Checking {index}/{count}: {refs}")
                    self.loading(f"Checking {index}/{count}", refs, index, count)

            wx.CallAfter(show)

        def work():
            try:
                result = optimizer.scan(
                    self.snapshot,
                    self.backend,
                    params,
                    cancel,
                    progress,
                    optimize=not self.check_only,
                )
                error = None
            except Exception as exc:
                result, error = None, str(exc)
            wx.CallAfter(self.scanned, result, error, cancel)

        self.pool.submit(work)

    def scanned(self, result, error, cancel):
        if self.closed or cancel is not self.cancel:
            return
        self.busy = False
        self.activity.Stop()
        self.progress_title.SetLabel(
            "Analysis complete" if not error and not cancel.is_set() else "Analysis stopped"
        )
        self.scan_button.Enable()
        if cancel.is_set() or error:
            self.status.SetLabel("Cancelled; no changes applied." if cancel.is_set() else error)
            return
        self.proposals = result["proposals"]
        observations = dict(result["observations"])
        observations.update(
            {p["candidate"].code: p["candidate"] for p in self.proposals if p.get("candidate")}
        )
        self.report.update_assembly_observations(observations)
        self.snapshot = copy.deepcopy(self.report.result)
        if self.check_only:
            self.proposals = [
                dict(
                    row=row,
                    current=result["observations"].get(row["lcsc"]),
                    candidate=None,
                    before=None,
                    after=None,
                    reason="Assembly observation only",
                )
                for row in self.snapshot["lines"]
            ]
        available = 0
        for proposal in self.proposals:
            row, current, candidate = (
                proposal["row"],
                proposal.get("current"),
                proposal.get("candidate"),
            )
            index = self.table.InsertItem(self.table.GetItemCount(), ", ".join(row["references"]))
            before, after = proposal.get("before"), proposal.get("after")

            def usd(value):
                return "Unknown" if value is None else f"{value:.4f}"

            values = [
                row["lcsc"] or "Unassigned",
                current.assembly_tier if current else "Unknown",
                str(current.assembly_stock)
                if current and current.assembly_stock is not None
                else "Unknown",
                f"{candidate.code} / {candidate.mpn}" if candidate else "",
                usd(before),
                usd(after),
                usd(after - before) if before is not None and after is not None else "Unknown",
                proposal["reason"],
            ]
            for col, value in enumerate(values, 1):
                self.table.SetItem(index, col, value)
            self.table.SetItemTextColour(index, GREEN if candidate else GOLD)
            if candidate:
                available += 1
                if self.assign_mode:
                    self.table.CheckItem(index, True)
        self.apply_button.Enable(available > 0)
        if self.assign_mode:
            self.phase.SetLabel(
                f"{available} verified equivalents selected. Uncheck any to keep unchanged."
            )
        self.status.SetLabel(
            f"{available} verified Basic proposals. Check the rows to apply. "
            "Positive difference costs more; negative difference saves component cost."
            if not self.check_only
            else "Assembly stock and classification checked; component information unchanged."
        )

    def apply(self, event=None):
        if self.busy or self.applying:
            return
        chosen = [
            p
            for i, p in enumerate(self.proposals)
            if self.table.IsItemChecked(i) and p.get("candidate")
        ]
        if not chosen:
            self.status.SetLabel("Check the proposals you want to apply first.")
            return
        if self.report.result != self.snapshot:
            self.status.SetLabel(
                "BOM changed since analysis. Close and reopen optimization before applying."
            )
            return
        removed = {ref for proposal in chosen for ref in proposal["row"]["references"]}
        for proposal in chosen:
            candidate = proposal["candidate"]
            per_board = sum(
                len(p["row"]["references"]) for p in chosen if p["candidate"].code == candidate.code
            )
            per_board += sum(
                len(set(row["references"]) - removed)
                for row in self.snapshot["lines"]
                if row["lcsc"] == candidate.code
            )
            demand = math.ceil(
                per_board * self.snapshot["boards"] * (1 + self.snapshot["spares_percent"] / 100)
            )
            _, order = optimizer.assembly_cost(candidate, demand)
            if order is None or (
                self.parameters.require_stock
                and (candidate.assembly_stock is None or candidate.assembly_stock < order)
            ):
                self.status.SetLabel(
                    candidate.code + ": insufficient stock for the combined selected BOM quantity"
                )
                return
            proposal["aggregate_order"] = order
        components = self.report.host.components
        if components.assignment and not components.assignment.detach():
            self.status.SetLabel("Finish the active component assignment first.")
            return
        self.applying = True
        self.changes = []
        self.scan_button.Disable()
        self.apply_button.Disable()
        self.queue = chosen
        self.apply_total = len(chosen)
        self.table.Disable()
        for control in (self.scope, self.tolerance, self.stock, self.dielectric):
            control.Disable()
        self.loading("Applying component updates", completed=0, total=self.apply_total)
        self.next_assignment()

    def next_assignment(self):
        if not self.queue or self.cancel.is_set():
            self.finish_application()
            return
        proposal = self.queue.pop(0)
        components = self.report.host.components

        def validate(checked):
            assembly = self.backend.assembly.exact(checked.code, self.session.cancel)
            if self.parameters.library_tier == "basic" and assembly.assembly_tier != "Basic":
                raise ValueError("Replacement is no longer classified Basic")
            if self.parameters.require_stock and (
                assembly.stock is None
                or assembly.stock < proposal.get("aggregate_order", proposal["order"])
            ):
                raise ValueError("Replacement has insufficient JLCPCB assembly stock")
            issues = optimizer.compatible(proposal["settings"], checked, self.parameters)
            if issues:
                raise ValueError("Replacement changed since analysis: " + "; ".join(issues))

        self.session = BomAssignmentSession(
            self.report,
            components,
            proposal["row"],
            self.assigned,
            validator=validate,
            progress=self.assignment_progress,
        )
        components.assignment = self.session
        self.current = proposal
        refs = ", ".join(proposal["row"]["references"])
        self.status.SetLabel("Applying: " + refs)
        self.loading(
            f"Updating {len(self.changes) + 1}/{self.apply_total}",
            refs,
            len(self.changes),
            self.apply_total,
        )
        if not self.session.expected or not self.session.schematic:
            self.session.done(
                None, "A saved root schematic and captured source references are required"
            )
            return
        self.session.set_part(proposal["candidate"])

    def assigned(self, properties, error):
        if properties:
            self.changes.append((self.current["row"]["references"], properties))
        if error:
            self.queue = []
            self.finish_application(error)
            return
        self.next_assignment()

    def finish_application(self, error=None):
        self.session = None
        self.progress_bar.SetValue(len(self.changes))
        if self.changes:
            self.loading(
                "Updating affected BOM rows and totals",
                completed=len(self.changes),
                total=self.apply_total,
            )
            self.report.refresh_assignments(
                self.changes,
                on_complete=lambda refresh_error: self.application_finished(error or refresh_error),
            )
        else:
            self.application_finished(error)

    def application_finished(self, error=None):
        if self.closed:
            return
        self.applying = False
        self.activity.Stop()
        self.progress_title.SetLabel(
            f"{len(self.changes)}/{self.apply_total} component groups updated"
        )
        self.progress_title.SetForegroundColour("#ff8585" if error else GREEN)
        self.phase.SetLabel(
            str(error) if error else "Finished. Save the PCB to retain field changes."
        )
        self.status.SetLabel(
            (str(error) + " | " if error else "")
            + f"{len(self.changes)} groups updated. Close to view the refreshed BOM."
        )
        self.scan_button.Disable()
        self.apply_button.Disable()
        self.table.Enable()
        self.Layout()

    def on_cancel(self, event=None):
        self.cancel.set()
        if self.session:
            self.session.request_cancel()
        elif self.applying and self.report.working:
            self.report.on_cancel()
        if self.busy and not self.applying:
            self.busy = False
            self.activity.Stop()
            self.progress_title.SetLabel("Cancelled")
            self.scan_button.Enable()
            self.status.SetLabel("Cancelled; no replacements applied.")
            return
        self.status.SetLabel("Cancellation requested; an active atomic assignment finishes safely.")

    def on_close(self, event=None):
        if self.applying:
            self.on_cancel()
            return
        self.cancel.set()
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.EndModal(wx.ID_CLOSE)
