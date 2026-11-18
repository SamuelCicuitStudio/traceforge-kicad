"""BOM-row LCSC research and explicit reference-scoped information assignment."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import wx

from . import component_info, component_occurrences, component_operations, supplier_records
from .cancellation import OperationCancelled


class BomAssignmentSession:
    """Assignment context for the existing Components tab; no additional window or browser."""

    def __init__(self, report, components, row, on_complete=None, validator=None, progress=None):
        self.operation_owner = self
        self.progress = progress
        self.validator = validator
        self.on_complete = on_complete
        self.report = report
        self.components = components
        self.panel = components.catalog_panel
        self.status = components.status
        self.closed = self.applying = False
        self.cancel = threading.Event()
        self.commit_lock = threading.Lock()
        self.committing = False
        refs = set(row["references"])
        self.expected = component_occurrences.expand(report.result.get("source_parts", []), refs)
        self.references = sorted(p["reference"] for p in self.expected)
        self.schematic = report.result.get("schematic")
        if not self.schematic and report.board_file:
            candidate = Path(report.board_file).with_suffix(".kicad_sch")
            self.schematic = str(candidate) if candidate.is_file() else None
        old = self.expected[0] if self.expected else {}
        label = (
            "Set information for "
            + ", ".join(self.references)
            + " | Keep value "
            + str(old.get("value", ""))
            + " | Keep footprint "
            + str(old.get("footprint", ""))
        )
        components.assignment_label.SetLabel(label)
        components.assignment_label.SetToolTip(label)
        components.assignment_bar.Show()
        self.panel.use_button.SetLabel("Set information for " + ", ".join(self.references))
        self.panel.use_button.Enable()
        components.Layout()

    def notify_progress(self, phase):
        def show():
            if not self.closed and self.applying and not getattr(self, "dismissed", False):
                self.current_phase = phase
                self.status.SetLabel(phase)
                self.panel.loading_activity.Start()
                self.panel.loading_label.SetLabel(phase)
                if self.progress:
                    self.progress(phase)

        wx.CallAfter(show)

    def heartbeat(self):
        if self.closed or not self.applying or getattr(self, "dismissed", False):
            return
        elapsed = int(time.monotonic() - self.started_at)
        self.panel.loading_label.SetLabel(f"{self.current_phase} | {elapsed}s")
        self.heartbeat_call = wx.CallLater(500, self.heartbeat)

    def set_part(self, part):
        if self.applying:
            return
        if not self.expected:
            self.status.SetLabel(
                "Recalculate the BOM first to capture the current component fields."
            )
            return
        if not self.schematic:
            self.status.SetLabel(
                "Choose the saved root schematic in BOM Cost before assigning project information."
            )
            return
        if not component_operations.gate(self.components).acquire(
            self.operation_owner, "Assigning component information"
        ):
            self.status.SetLabel("Finish or cancel the active component operation first.")
            return
        self.cancel = threading.Event()
        self.applying = True
        self.started_at = time.monotonic()
        self.current_phase = "Starting component update"
        self.heartbeat_call = wx.CallLater(500, self.heartbeat)
        self.report.calculate.Disable()
        self.panel.use_button.Disable()
        self.panel.loading_activity.Start()
        self.panel.loading_label.SetLabel("Starting component update")
        self.status.SetLabel("Updating reference information; geometry and routing stay intact...")
        report = self.report
        expected = self.expected
        schematic = self.schematic

        def work():
            journal = None
            plan = None
            try:
                self.notify_progress("Loading selected component information")
                checked = (
                    supplier_records.refresh_saved(part, expected)
                    if getattr(part, "verification_source", "") == "saved project information"
                    else self.panel.backend.details(part, self.cancel)
                )
                if checked.code != part.code or checked.mpn != part.mpn:
                    raise ValueError("Selected supplier identity changed; search again")
                if self.cancel.is_set():
                    raise OperationCancelled("Replacement cancelled")
                self.notify_progress("Verifying equivalent ratings and available stock")
                component_info.validate_passive(expected, checked)
                if self.validator:
                    self.validator(checked)
                props = component_info.selected_properties(checked, Path(schematic).parent)
                # Exact identity assignment retains known ratings and alternate supplier codes.
                if self.validator and all(
                    component_info.schema.properties(p.get("properties", {}))
                    .get("MPN", "")
                    .casefold()
                    == checked.mpn.casefold()
                    for p in expected
                ):
                    prior = component_info.schema.properties(expected[0].get("properties", {}))
                    props = {key: value or prior.get(key, "") for key, value in props.items()}
                token = None
                if report.native:
                    info = report.host.api.call(lambda: report.native("info"))
                    if Path(info["board"]).resolve().parent != Path(schematic).resolve().parent:
                        raise ValueError("Active PCB belongs to another project")
                    preview = report.host.api.call(
                        lambda: report.native(
                            "component_info_preview",
                            refs=[p["reference"] for p in expected],
                            properties=props,
                            expected=expected,
                        )
                    )
                    token = preview["token"]
                self.notify_progress("Preparing schematic field updates")
                plan = component_info.plan(
                    schematic, expected, props, cancel=self.cancel, progress=self.notify_progress
                )
                with self.commit_lock:
                    if self.cancel.is_set():
                        raise OperationCancelled(
                            "Assignment cancelled before writing component information"
                        )
                    self.committing = True
                self.notify_progress("Saving schematic information")
                journal = component_info.install(plan)["journal"]
                if report.native:
                    self.notify_progress("Updating PCB component fields")
                    report.host.api.call(lambda: report.native("component_info_apply", token=token))
                result, error = props, None
            except Exception as exc:
                if journal:
                    try:
                        component_info.rollback(plan, journal)
                    except Exception as rollback:
                        exc = RuntimeError(str(exc) + "; " + str(rollback))
                result, error = None, str(exc)
            if not self.closed:
                wx.CallAfter(self.done, result, error)

        report.executor.submit(work)

    def done(self, result, error):
        if self.closed:
            return
        self.applying = False
        self.committing = False
        if getattr(self, "heartbeat_call", None):
            self.heartbeat_call.Stop()
        if self.report.closed:
            component_operations.gate(self.components).release(self.operation_owner)
            self.detach()
            return
        self.panel.loading_activity.Stop()
        self.panel.loading_label.SetLabel("Failed" if error else "Component information saved")
        self.report.calculate.Enable()
        if error and not self.on_complete:
            component_operations.gate(self.components).release(self.operation_owner)
        if error and self.on_complete:
            self.detach()
            self.on_complete(None, error)
            return
        if error:
            self.panel.use_button.Enable()
            if getattr(self, "dismissed", False):
                self.report.message(
                    "Replacement cancelled; no pending assignment remains.", "warning"
                )
                self.detach()
                return
            self.status.SetLabel(error)
            self.status.SetForegroundColour("#ffd166" if self.cancel.is_set() else "#ff8585")
            return
        self.report.status.SetLabel(
            "Updated component information. Save PCB to retain its field changes."
        )
        self.detach()
        if self.on_complete:
            self.on_complete(result, None)
            return
        self.report.host.activate_tool("manufacturing.cost")

        def refreshed(error):
            self.panel.loading_activity.Stop()
            self.panel.loading_label.SetLabel("Refresh failed" if error else "Update complete")
            component_operations.gate(self.components).release(self.operation_owner)

        self.panel.loading_activity.Start()
        self.panel.loading_label.SetLabel("Refreshing affected BOM rows and totals")
        self.report.refresh_assignments([(self.references, result)], on_complete=refreshed)

    def request_cancel(self):
        # Manual replacement leaves Components immediately; its worker retains
        # the operation owner until cancellation/commit and refresh finish.
        if not self.on_complete:
            self.dismissed = True
            if self.components.assignment is self:
                self.components.assignment = None
                self.components.assignment_bar.Hide()
                self.panel.use_button.SetLabel("Use in project")
                self.panel.use_button.Enable()
                self.components.Layout()
            self.report.host.activate_tool("manufacturing.cost")
        with self.commit_lock:
            committing = self.committing
            if not committing:
                self.cancel.set()
        if not self.applying:
            component_operations.gate(self.components).release(self.operation_owner)
            self.detach()
        message = (
            "Replacement window closed; finishing the active transaction safely."
            if committing
            else "Replacement cancelled; stopping pending work."
        )
        if self.on_complete:
            self.status.SetLabel(message)
        else:
            self.report.message(message, "warning")
        return not committing

    def detach(self):
        if self.applying:
            self.status.SetLabel("Finishing the information transaction...")
            return False
        self.closed = True
        if self.components.assignment is self:
            self.components.assignment = None
            self.components.assignment_bar.Hide()
            self.panel.use_button.SetLabel("Use in project")
            self.panel.use_button.Enable()
            self.components.Layout()
        return True
