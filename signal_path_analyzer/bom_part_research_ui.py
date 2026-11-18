"""BOM-row LCSC research and explicit reference-scoped information assignment."""

from __future__ import annotations

import threading
from pathlib import Path

import wx

from . import component_info
from .cancellation import OperationCancelled


class BomAssignmentSession:
    """Assignment context for the existing Components tab; no additional window or browser."""

    def __init__(self, report, components, row, on_complete=None, validator=None, progress=None):
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
        self.expected = [p for p in report.result.get("source_parts", []) if p["reference"] in refs]
        self.schematic = report.result.get("schematic")
        if not self.schematic and report.board_file:
            candidate = Path(report.board_file).with_suffix(".kicad_sch")
            self.schematic = str(candidate) if candidate.is_file() else None
        old = self.expected[0] if self.expected else {}
        label = (
            "Set information for "
            + ", ".join(row["references"])
            + " | Keep value "
            + str(old.get("value", ""))
            + " | Keep footprint "
            + str(old.get("footprint", ""))
        )
        components.assignment_label.SetLabel(label)
        components.assignment_label.SetToolTip(label)
        components.assignment_bar.Show()
        self.panel.use_button.SetLabel("Set information for " + ", ".join(row["references"]))
        self.panel.use_button.Enable()
        components.Layout()

    def notify_progress(self, phase):
        if self.progress:

            def show():
                if not self.closed:
                    self.progress(phase)

            wx.CallAfter(show)

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
        self.cancel = threading.Event()
        self.applying = True
        self.report.calculate.Disable()
        self.panel.use_button.Disable()
        self.status.SetLabel("Updating reference information; geometry and routing stay intact...")
        report = self.report
        expected = self.expected
        schematic = self.schematic

        def work():
            journal = None
            plan = None
            try:
                self.notify_progress("Loading selected component information")
                checked = self.panel.backend.details(part, self.cancel)
                if checked.code != part.code or checked.mpn != part.mpn:
                    raise ValueError("Selected supplier identity changed; search again")
                self.notify_progress("Verifying equivalent ratings and available stock")
                component_info.validate_passive(expected, checked)
                if self.validator:
                    self.validator(checked)
                props = component_info.selected_properties(checked, Path(schematic).parent)
                component_info.check_closed(schematic)
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
                plan = component_info.plan(schematic, expected, props)
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
        if self.report.closed:
            self.detach()
            return
        self.report.calculate.Enable()
        if error and self.on_complete:
            self.detach()
            self.on_complete(None, error)
            return
        if error:
            self.panel.use_button.Enable()
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
        self.report.refresh_assignment([p["reference"] for p in self.expected], result)

    def request_cancel(self):
        with self.commit_lock:
            if self.committing:
                self.status.SetLabel(
                    "Finishing the atomic information update; it will not be interrupted halfway."
                )
                return False
            self.cancel.set()
        self.status.SetLabel("Cancellation requested; component information will not be written.")
        return True

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
