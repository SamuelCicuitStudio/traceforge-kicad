"""Project-aware component research, exact CAD staging and local-library installation."""

from __future__ import annotations

import json
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import wx

from . import component_library as library
from . import component_runtime as runtime
from . import component_schema as schema
from . import lcsc_retail


class ComponentsPanel(wx.Panel):
    def __init__(self, parent, host, native, board_file):
        super().__init__(parent)
        if host.dark:
            self.SetBackgroundColour("#222C3A")
            self.SetForegroundColour("#E5EDF8")
        self.host, self.native = host, native
        self.board_file = str(board_file or "")
        self.project = None
        self.stage = None
        self.plan = None
        self.last_symbol_id = ""
        self.assignment = None
        self.research = None
        self.candidates = []
        self.closed = self.working = self.installing = False
        self.committing = False
        self.commit_lock = threading.Lock()
        self.worker = None
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="traceforge-components"
        )
        self.config = runtime.settings()
        outer = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.project_label = wx.StaticText(self, label="Project: choose a saved schematic or PCB")
        bar.Add(self.project_label, 1, wx.ALIGN_CENTER_VERTICAL)
        self.selector = wx.Choice(
            self, choices=["Search / details", "Assets / import", "Project library"]
        )
        self.selector.SetSelection(0)
        bar.Add(self.selector, 0, wx.RIGHT, 5)
        settings = wx.Button(self, label="Runtime settings")
        settings.Bind(wx.EVT_BUTTON, self.on_settings)
        bar.Add(settings)
        outer.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
        self.book = wx.Simplebook(self)
        self.search_page = wx.Panel(self.book)
        self.asset_page = wx.ScrolledWindow(self.book)
        self.asset_page.SetScrollRate(0, 12)
        self.library_page = wx.Panel(self.book)
        self.book.AddPage(self.search_page, "Search")
        self.book.AddPage(self.asset_page, "Assets")
        self.book.AddPage(self.library_page, "Library")
        self.selector.Bind(wx.EVT_CHOICE, self.on_tool)
        self.build_search()
        self.build_assets()
        lib_box = wx.BoxSizer(wx.VERTICAL)
        self.inventory = wx.TextCtrl(self.library_page, style=wx.TE_MULTILINE | wx.TE_READONLY)
        lib_box.Add(self.inventory, 1, wx.EXPAND | wx.ALL, 6)
        updates = wx.Button(self.library_page, label="Preview / update selected PCB footprints")
        updates.Bind(wx.EVT_BUTTON, self.on_board_updates)
        updates.Enable(native is not None)
        lib_box.Add(updates, 0, wx.ALL, 6)
        self.library_page.SetSizer(lib_box)
        outer.Add(self.book, 1, wx.EXPAND)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.status = wx.StaticText(
            self, label="Search or enter an exact LCSC code and MPN under Assets."
        )
        footer.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.stop = wx.Button(self, label="Cancel operation")
        self.stop.Bind(wx.EVT_BUTTON, self.on_cancel)
        footer.Add(self.stop)
        outer.Add(footer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(outer)
        self.load_project()

    def on_board_updates(self, event=None):
        from .component_update_ui import ComponentUpdatePanel

        window = wx.Frame(
            self.host,
            title="TraceForge — selected footprint library updates",
            size=(940, 680),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        panel = ComponentUpdatePanel(window, self.host, self.native)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(panel, 1, wx.EXPAND)
        window.SetSizer(box)
        from .workspace_ui import show_utility

        show_utility(self.host, window)

    def build_search(self):
        from .lcsc_research_ui import ResearchPanel

        box = wx.BoxSizer(wx.VERTICAL)
        self.assignment_bar = wx.Panel(self.search_page)
        banner = wx.BoxSizer(wx.HORIZONTAL)
        self.assignment_label = wx.StaticText(
            self.assignment_bar, label="", style=wx.ST_ELLIPSIZE_END
        )
        self.assignment_label.SetMinSize((1, -1))
        self.assignment_label.SetForegroundColour("#7dcfff")
        banner.Add(self.assignment_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        back = wx.Button(self.assignment_bar, label="Return to BOM")
        back.Bind(wx.EVT_BUTTON, self.return_to_bom)
        banner.Add(back)
        self.assignment_bar.SetSizer(banner)
        box.Add(self.assignment_bar, 0, wx.EXPAND | wx.ALL, 6)
        self.assignment_bar.Hide()
        self.catalog_panel = ResearchPanel(self.search_page, self.on_research_part)
        self.catalog_panel.cancel_action = self.on_cancel
        box.Add(self.catalog_panel, 1, wx.EXPAND)
        self.search_page.SetSizer(box)

    def on_research_part(self, part):
        if self.assignment:
            self.assignment.set_part(part)
        else:
            self.use_research_part(part)

    def begin_bom_assignment(self, report, row, replacement=False):
        from .bom_part_research_ui import BomAssignmentSession

        if self.assignment and not self.assignment.detach():
            return
        self.status.SetForegroundColour("#e5edf8")
        self.assignment = BomAssignmentSession(report, self, row)
        self.catalog_panel.reset_context("" if replacement else (row["mpn"] or row["lcsc"]))
        self.host.activate_tool("components.search")
        if replacement:
            self.prepare_replacement(row)
        elif self.catalog_panel.query.GetValue():
            self.catalog_panel.search()
        self.message(
            "Select the exact part, then Set information. Only the displayed references change."
        )

    def prepare_replacement(self, row):
        from . import lcsc_research_backend as catalog
        from . import replacement_search as replacement

        panel, session = self.catalog_panel, self.assignment
        self.message("Loading replacement criteria from the current part...")

        def work(cancel):
            supplier = None
            if row.get("lcsc"):
                try:
                    candidate = panel.backend.exact(row["lcsc"], cancel)
                    if not row.get("mpn") or candidate.mpn.casefold() == row["mpn"].casefold():
                        supplier = candidate
                except catalog.Cancelled:
                    raise
                except catalog.LCSCError:
                    pass
            if supplier is None and row.get("mpn"):
                try:
                    matches = panel.backend.search(catalog.Query(keyword=row["mpn"]), cancel).parts
                    maker = row.get("manufacturer", "")
                    exact = [
                        part
                        for part in matches
                        if part.mpn.casefold() == row["mpn"].casefold()
                        and maker
                        and schema.fold(part.manufacturer) == schema.fold(maker)
                    ]
                    if exact:
                        supplier = panel.backend.details(exact[0], cancel)
                except catalog.Cancelled:
                    raise
                except catalog.LCSCError:
                    pass
            settings = replacement.current_settings(session.expected, supplier)
            categories = panel.backend.categories(cancel)[0]
            category = replacement.find_category(
                categories, settings["kind"], settings["category_hint"]
            )
            query = catalog.Query(
                in_stock=True,
                category_id=category.id if category else None,
                category_ids=catalog.category_leaves(categories, category.id) if category else (),
            )
            groups = panel.backend.filter_groups(query, cancel)[0]
            pending, applied, unmatched = replacement.choose_filters(groups, settings)
            return categories, query, groups, pending, applied, unmatched

        def done(data):
            if self.assignment is not session or session.closed:
                return
            categories, query, groups, pending, applied, unmatched = data
            panel.set_categories(categories)
            panel.category_id, panel.category_ids = query.category_id, query.category_ids
            panel.pending = pending
            panel.stock.SetValue(True)
            panel.show_filters(groups)
            panel.search()
            text = "Replacement filters: " + (
                "; ".join(applied) or "choose the required specifications"
            )
            if unmatched:
                text += ". Review fields not preset: " + "; ".join(unmatched)
            self.message(text)

        panel.task("replacement", work, done)

    def return_to_bom(self, event=None):
        if self.assignment and not self.assignment.detach():
            return
        self.host.activate_tool("manufacturing.cost")

    def use_research_part(self, part):
        self.research = dict(
            part.cad_record(),
            product_url=part.product_url,
            datasheet=part.datasheet_url,
            package=part.package,
        )
        for key, value in (
            ("lcsc", part.code),
            ("mpn", part.mpn),
            ("manufacturer", part.manufacturer),
            ("Package", part.package),
        ):
            self.fields[key].SetValue(value if value != "Unknown" else "")
        known = schema.properties(
            dict(part.specs, Datasheet=part.datasheet_url, Description=part.description)
        )
        for key in self.fields:
            if key not in ("lcsc", "mpn", "manufacturer", "value", "Package"):
                self.fields[key].SetValue(known.get(key, ""))
        category = part.category.casefold()
        passive = next(
            (
                i
                for i, token in (
                    (1, "resistor"),
                    (2, "capacitor"),
                    (3, "inductor"),
                    (4, "ferrite"),
                    (5, "led"),
                )
                if token in category
            ),
            0,
        )
        self.reuse_symbol.SetSelection(0)
        self.reuse_footprint.SetSelection(0)
        self.category.SetSelection(passive)
        self.on_category()
        value = next(
            (
                v
                for k, v in part.specs.items()
                if k.casefold()
                in ("resistance", "capacitance", "inductance", "impedance", "impedance @ frequency")
            ),
            part.mpn,
        )
        self.fields["value"].SetValue(str(value))
        self.stage = None
        self.checked.SetValue(False)
        self.model_checked.SetValue(False)
        self.selector.SetSelection(1)
        self.book.SetSelection(1)
        self.message(
            "LCSC identity copied to Assets / import. Review package and select assets to stage."
        )

    def build_assets(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(cols=4, hgap=7, vgap=7)
        form.AddGrowableCol(1)
        form.AddGrowableCol(3)
        self.fields = {}
        for key, label in [
            ("lcsc", "LCSC code"),
            ("mpn", "Exact MPN"),
            ("manufacturer", "Manufacturer"),
            ("value", "Value"),
            ("Tolerance", "Tolerance"),
            ("Voltage", "Voltage"),
            ("Power", "Power"),
            ("Current", "Current"),
            ("Dielectric", "Dielectric"),
            ("Package", "Package"),
            ("Saturation Current", "Saturation current"),
            ("DCR", "DC resistance"),
            ("Impedance Frequency", "Impedance frequency"),
            ("Datasheet", "Datasheet URL"),
            ("Description", "Description"),
        ]:
            form.Add(wx.StaticText(self.asset_page, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = wx.TextCtrl(self.asset_page)
            control.Bind(wx.EVT_TEXT, self.on_changed)
            self.fields[key] = control
            form.Add(control, 1, wx.EXPAND)
        outer.Add(form, 0, wx.EXPAND | wx.ALL, 8)
        self.category = wx.Choice(
            self.asset_page,
            choices=[
                "Custom / IC / connector",
                "Resistor",
                "Capacitor",
                "Inductor",
                "Ferrite bead",
                "Simple LED",
                "Special passive",
            ],
        )
        self.category.SetSelection(0)
        self.category.Bind(wx.EVT_CHOICE, self.on_category)
        outer.Add(self.category, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        locate = wx.Button(self.asset_page, label="Locate existing exact part")
        locate.Bind(wx.EVT_BUTTON, self.on_locate)
        outer.Add(locate, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.symbol_library = wx.Choice(self.asset_page)
        self.footprint_library = wx.Choice(self.asset_page)
        self.reuse_symbol = wx.ComboBox(self.asset_page, style=wx.CB_READONLY)
        self.reuse_footprint = wx.ComboBox(self.asset_page, style=wx.CB_READONLY)
        for label, control in [
            ("Project symbol library", self.symbol_library),
            ("Project footprint library", self.footprint_library),
            ("Reuse existing symbol", self.reuse_symbol),
            ("Reuse existing footprint", self.reuse_footprint),
        ]:
            outer.Add(wx.StaticText(self.asset_page, label=label), 0, wx.LEFT | wx.RIGHT, 8)
            outer.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.symbol_library.Bind(wx.EVT_CHOICE, lambda event: self.fill_assets())
        self.footprint_library.Bind(wx.EVT_CHOICE, lambda event: self.fill_assets())
        self.reuse_symbol.Bind(wx.EVT_COMBOBOX, self.on_changed)
        self.reuse_footprint.Bind(wx.EVT_COMBOBOX, self.on_changed)
        options = wx.BoxSizer(wx.HORIZONTAL)
        self.asset_mode = wx.Choice(
            self.asset_page,
            choices=[
                "Symbol + footprint",
                "Footprint only",
                "Symbol only",
                "Existing assets / STEP only",
            ],
        )
        self.asset_mode.SetSelection(0)
        self.asset_mode.Bind(wx.EVT_CHOICE, self.on_changed)
        options.Add(self.asset_mode, 1, wx.RIGHT, 10)
        self.want_step = wx.CheckBox(self.asset_page, label="Download STEP candidate")
        self.want_step.Bind(wx.EVT_CHECKBOX, self.on_changed)
        options.Add(self.want_step, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(options, 0, wx.EXPAND | wx.ALL, 8)
        self.model_checked = wx.CheckBox(
            self.asset_page,
            label="STEP package/orientation checked: link with the XYZ transform below",
        )
        self.model_checked.Bind(wx.EVT_CHECKBOX, self.on_changed)
        outer.Add(self.model_checked, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        transform_row = wx.BoxSizer(wx.HORIZONTAL)
        self.model_offset = []
        self.model_rotation = []
        for label, controls, minimum, maximum in [
            ("Offset mm", self.model_offset, -1000, 1000),
            ("Rotation deg", self.model_rotation, -360, 360),
        ]:
            transform_row.Add(
                wx.StaticText(self.asset_page, label=label),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                5,
            )
            for axis in "XYZ":
                transform_row.Add(
                    wx.StaticText(self.asset_page, label=axis),
                    0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                    3,
                )
                control = wx.SpinCtrlDouble(
                    self.asset_page, min=minimum, max=maximum, initial=0, inc=0.1, size=(72, -1)
                )
                control.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_changed)
                control.Bind(wx.EVT_TEXT, self.on_changed)
                controls.append(control)
                transform_row.Add(control, 0, wx.RIGHT, 6)
        outer.Add(transform_row, 0, wx.ALL, 8)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [
            ("Stage downloads", self.on_stage),
            ("Preview CAD", self.on_preview),
            ("Build import plan", self.on_plan),
        ]:
            button = wx.Button(self.asset_page, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 6)
        self.apply = wx.Button(self.asset_page, label="Add to project library")
        self.apply.Bind(wx.EVT_BUTTON, self.on_install)
        self.apply.Disable()
        actions.Add(self.apply)
        outer.Add(actions, 0, wx.ALL, 8)
        self.checked = wx.CheckBox(
            self.asset_page, label="Pin/pad mapping and selected package checked"
        )
        self.checked.Bind(wx.EVT_CHECKBOX, self.on_changed)
        outer.Add(self.checked, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.plan_text = wx.TextCtrl(
            self.asset_page, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 180)
        )
        outer.Add(self.plan_text, 1, wx.EXPAND | wx.ALL, 8)
        self.copy_symbol = wx.Button(self.asset_page, label="Copy symbol ID for Place Symbol (A)")
        self.copy_symbol.Bind(wx.EVT_BUTTON, self.on_copy_symbol)
        self.copy_symbol.Disable()
        outer.Add(self.copy_symbol, 0, wx.ALL, 8)
        self.asset_page.SetSizer(outer)

    def message(self, text, level=None):
        self.status.SetLabel(str(text))
        self.status.Wrap(max(350, self.GetClientSize().width - 160))
        self.Layout()

    def on_tool(self, event=None):
        self.book.SetSelection(self.selector.GetSelection())
        self.host.workspace_changed()

    def invalidate(self):
        self.plan = None
        self.apply.Disable()

    def on_changed(self, event=None):
        self.invalidate()
        self.last_symbol_id = ""
        if hasattr(self, "copy_symbol"):
            self.copy_symbol.Disable()
        if event:
            event.Skip()

    def on_category(self, event=None):
        self.invalidate()
        category = ["custom", "resistor", "capacitor", "inductor", "bead", "led", "custom"][
            self.category.GetSelection()
        ]
        suggestion = library.suggest_generic(self.reuse_symbol.GetStrings(), category)
        suggestion = suggestion or schema.passive_symbol(category)
        if suggestion:
            self.reuse_symbol.SetStringSelection(suggestion)
            self.message("Suggested " + suggestion + "; select and verify compatible pad geometry.")

    def on_locate(self, event=None):
        if not self.project:
            return
        record = library.existing_part(
            self.project["root"],
            self.fields["manufacturer"].GetValue(),
            self.fields["mpn"].GetValue(),
        )
        if not record:
            self.message("No exact manufacturer/MPN entry in this project's catalog or libraries.")
            return
        if record.get("status") == "ambiguous":
            self.last_symbol_id = ""
            self.copy_symbol.Disable()
            self.plan_text.SetValue(json.dumps(record, indent=2))
            self.message(
                "Several customized definitions match; select the intended existing asset."
            )
            return
        self.invalidate()
        for _key, control, asset in [
            ("symbols", self.symbol_library, "symbol"),
            ("footprints", self.footprint_library, "footprint"),
        ]:
            nickname = record.get(asset, "").split(":", 1)[0]
            if nickname:
                control.SetStringSelection(nickname)
        self.fill_assets()
        for field, control in (("symbol", self.reuse_symbol), ("footprint", self.reuse_footprint)):
            asset = record.get(field, "")
            if asset and not control.SetStringSelection(asset):
                self.message("Existing mapping uses another destination: " + asset)
                return
        self.last_symbol_id = record.get("symbol", "")
        self.copy_symbol.Enable(bool(self.last_symbol_id))
        self.plan_text.SetValue(json.dumps(record, indent=2))
        self.message("Existing exact mapping selected; shared library assets are preserved.")

    def load_project(self):
        self.invalidate()
        self.project = None
        self.last_symbol_id = ""
        self.copy_symbol.Disable()
        try:
            self.project = library.discover(self.board_file)
            self.project_label.SetLabel("Project: " + Path(self.board_file).stem)
            for key, control in [
                ("symbols", self.symbol_library),
                ("footprints", self.footprint_library),
            ]:
                rows = self.project[key]
                control.Set([x["nickname"] for x in rows])
                chosen = self.project["symbol" if key == "symbols" else "footprint"]
                if chosen:
                    control.SetStringSelection(chosen["nickname"])
            self.fill_assets()
        except (OSError, ValueError, KeyError) as exc:
            self.project = None
            self.message("Project libraries unavailable: " + str(exc))

    def fill_assets(self):
        self.invalidate()
        if not self.project:
            return
        try:
            sym, fp = self.destinations()
            names = library.symbol_names(sym["path"])
            fps = library.footprint_names(fp["path"])
            builtins = [
                schema.passive_symbol(c)
                for c in schema.SCHEMA["categories"]
                if schema.passive_symbol(c)
            ]
            self.reuse_symbol.Set([""] + [sym["nickname"] + ":" + n for n in names] + builtins)
            self.reuse_symbol.SetSelection(0)
            self.reuse_footprint.Set([""] + [fp["nickname"] + ":" + n for n in fps])
            self.reuse_footprint.SetSelection(0)
            self.inventory.SetValue(
                "Symbol library: "
                + sym["path"]
                + "\nFootprint library: "
                + fp["path"]
                + "\n\n"
                + f"{len(names)} symbols; {len(fps)} footprints\n\n"
                + "Registered exact parts: "
                + str(len(library.catalog(self.project["root"]).get("parts", {})))
            )
        except (OSError, ValueError, KeyError, IndexError) as exc:
            self.message(str(exc))

    def destinations(self):
        if not self.project:
            raise ValueError("Open a saved PCB first")
        if self.symbol_library.GetSelection() < 0 or self.footprint_library.GetSelection() < 0:
            raise ValueError("Select project library destinations once")
        return (
            self.project["symbols"][self.symbol_library.GetSelection()],
            self.project["footprints"][self.footprint_library.GetSelection()],
        )

    def submit(self, function, done):
        if self.working:
            self.message("A component operation is already running.")
            return
        self.worker = runtime.Worker(self.config)
        self.working = True
        self.message("Working...")
        worker = self.worker

        def work():
            try:
                result, error = function(worker), None
            except Exception as exc:
                result, error = None, exc
            if not self.closed:
                wx.CallAfter(finish, result, error)

        def finish(result, error):
            if self.closed:
                return
            self.working = False
            self.installing = False
            self.committing = False
            if error:
                self.message(str(error))
            elif worker.cancel.is_set():
                self.message("Cancelled. Active project assets were not changed.")
            else:
                done(result)

        self.executor.submit(work)

    def on_cancel(self, event=None):
        self.catalog_panel.cancel_pending()
        if self.assignment and self.assignment.applying:
            self.assignment.request_cancel()
            return
        with self.commit_lock:
            if self.committing:
                self.message("Finishing the recoverable library transaction...")
                return
            if self.worker:
                self.worker.cancel.set()
        self.invalidate()
        self.message("Cancellation requested; active libraries are preserved.")

    def on_settings(self, event=None):
        dialog = wx.Dialog(self, title="Component Research and CAD runtimes", size=(740, 360))
        box = wx.BoxSizer(wx.VERTICAL)
        controls = {}
        for key, label in [
            ("browser", "Component-browser folder"),
            ("node", "Node executable"),
            ("helpers", "PCB download-helper scripts folder"),
            ("python", "Converter Python executable"),
        ]:
            box.Add(wx.StaticText(dialog, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
            control = wx.TextCtrl(dialog, value=self.config.get(key, ""))
            box.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
            controls[key] = control
        box.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        dialog.SetSizer(box)
        if dialog.ShowModal() == wx.ID_OK:
            self.config = {key: control.GetValue().strip() for key, control in controls.items()}
            runtime.save_settings(self.config)
            self.message("Runtime paths saved for this user; KiCad Python was not modified.")
        dialog.Destroy()

    def show_details(self, result):
        self.message(result.get("reason") or "Component operation complete.")

    def on_datasheet(self, event=None):
        if self.research and self.research.get("datasheet"):
            url = self.research["datasheet"]
            self.submit(
                lambda worker: worker.browser("download_datasheet", url=url), self.show_details
            )
            return
        code = self.fields["lcsc"].GetValue().strip().upper()
        expected = self.fields["mpn"].GetValue().strip()
        if (
            self.research
            and "lcsc.com/" in self.research.get("source", "")
            and re.fullmatch(r"C[0-9]{2,}", code)
        ):
            # The product page may expose a document landing page rather than
            # PDF bytes. Resolve the exact part's direct supplier PDF URL.
            def work(worker):
                quote = lcsc_retail.lookup_pricing(code, lambda message: None)
                if expected and quote.get("mpn", "").casefold() != expected.casefold():
                    raise ValueError("LCSC code and requested datasheet MPN do not match.")
                if not quote.get("datasheet"):
                    raise ValueError("The exact LCSC record has no direct datasheet URL.")
                return worker.browser("download_datasheet", url=quote["datasheet"])

            self.submit(work, self.show_details)
            return
        if not self.research or not self.research.get("research_id"):
            self.message("Inspect the selected part first.")
            return
        rid = self.research["research_id"]
        self.submit(
            lambda worker: worker.browser("download_datasheet", research_id=rid), self.show_details
        )

    def on_stage(self, event=None):
        if not self.project:
            self.message("Choose a saved schematic or PCB project first.")
            return
        self.invalidate()
        self.stage = None
        self.checked.SetValue(False)
        self.model_checked.SetValue(False)
        code, mpn = (self.fields[k].GetValue().strip() for k in ["lcsc", "mpn"])
        mode = ["both", "footprint", "symbol", "none"][self.asset_mode.GetSelection()]
        if 1 <= self.category.GetSelection() <= 5:
            mode = "none" if self.reuse_footprint.GetValue().strip() else "footprint"
        root, step = self.project["root"], self.want_step.GetValue()

        def done(result):
            self.stage = result
            identity = result.get("source", {}).get("identity", {})
            if identity.get("manufacturer") and not self.fields["manufacturer"].GetValue():
                self.fields["manufacturer"].SetValue(identity["manufacturer"])
            self.plan_text.SetValue(
                "Staged assets (not installed):\n" + json.dumps(result, indent=2)
            )
            self.message(
                "Staged. Preview assets, check package/pin identity, then build import plan."
            )

        self.submit(lambda worker: worker.stage(root, code, mpn, mode, step), done)

    def on_preview(self, event=None):
        if not self.stage:
            self.message("Stage a component first.")
            return
        stage = dict(self.stage)
        cli = shutil.which("kicad-cli") or str(Path(sys.executable).parent / "kicad-cli.exe")

        def work(worker):
            out = Path(stage["staging"]) / "preview"
            out.mkdir(exist_ok=True)
            if stage.get("symbol"):
                worker.run([cli, "sym", "export", "svg", "-o", str(out), stage["symbol"]])
            if stage.get("footprint"):
                worker.run(
                    [
                        cli,
                        "fp",
                        "export",
                        "svg",
                        "-o",
                        str(out),
                        "-l",
                        "F.Cu,F.SilkS,F.Fab",
                        "--sp",
                        stage["footprint"],
                    ]
                )
            return [str(p) for p in out.glob("*.svg")]

        self.submit(work, self.show_preview)

    def show_preview(self, paths):
        if not paths:
            self.message("No drawable CAD assets; existing generic assets are preserved.")
            return
        import wx.svg

        dialog = wx.Dialog(
            self,
            title="KiCad asset preview - pin/pad review",
            size=(850, 640),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        box = wx.BoxSizer(wx.VERTICAL)
        choice = wx.Choice(dialog, choices=[Path(p).name for p in paths])
        choice.SetSelection(0)
        image = wx.StaticBitmap(dialog)
        box.Add(choice, 0, wx.EXPAND | wx.ALL, 6)
        box.Add(image, 1, wx.EXPAND | wx.ALL, 6)

        def draw(event=None):
            svg = wx.svg.SVGimage.CreateFromFile(paths[choice.GetSelection()])
            image.SetBitmap(svg.ConvertToScaledBitmap(wx.Size(790, 520)))
            dialog.Layout()

        choice.Bind(wx.EVT_CHOICE, draw)
        dialog.SetSizer(box)
        draw()
        dialog.ShowModal()
        dialog.Destroy()

    def on_plan(self, event=None):
        if self.working:
            return
        try:
            sym, fp = self.destinations()
            part = {key: control.GetValue().strip() for key, control in self.fields.items()}
            source = self.stage or {}
            if source and (source["mpn"] != part["mpn"] or source["lcsc"] != part["lcsc"].upper()):
                raise ValueError("Selected identity changed; stage the requested exact part again")
            if not self.checked.GetValue():
                raise ValueError(
                    "Check the package and pin/pad mapping before building the install plan"
                )
            category = ["custom", "resistor", "capacitor", "inductor", "bead", "led", "custom"][
                self.category.GetSelection()
            ]
            part["provenance"] = source.get("source", {})
            part["package_pin_map_reviewed"] = self.checked.GetValue()
            model = None
            if source.get("model"):
                model = dict(
                    path=source["model"],
                    checked=self.model_checked.GetValue(),
                    offset=[c.GetValue() for c in self.model_offset],
                    rotation=[c.GetValue() for c in self.model_rotation],
                )
            self.plan = library.plan_import(
                self.project["root"],
                part,
                sym,
                fp,
                candidate_symbol=source.get("symbol"),
                candidate_footprint=source.get("footprint"),
                reuse_symbol=self.reuse_symbol.GetValue(),
                reuse_footprint=self.reuse_footprint.GetValue(),
                category=category,
                model=model,
                placement_symbol=True,
            )
            self.plan_text.SetValue(
                "\n".join(self.plan["summary"])
                + "\n\nFiles to update:\n"
                + "\n".join(self.plan["writes"])
                + "\n\nLibrary-only: placed references, wiring and routing are unchanged."
            )
            self.apply.Enable()
            self.apply.SetLabel("Add to " + sym["nickname"])
            self.message("Ready to add the reviewed assets to " + sym["nickname"])
        except (OSError, ValueError, KeyError) as exc:
            self.invalidate()
            self.message(str(exc))

    def on_copy_symbol(self, event=None):
        if self.last_symbol_id and wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self.last_symbol_id))
            finally:
                wx.TheClipboard.Close()
            self.message("In Schematic Editor press A, then paste " + self.last_symbol_id)

    def on_install(self, event=None):
        if not self.plan or self.working:
            return
        plan = self.plan
        self.installing = True
        self.invalidate()

        def work(worker):
            if self.native:
                info = self.host.api.call(lambda: self.native("info"))
                if Path(info["board"]).resolve() != Path(self.board_file).resolve():
                    raise ValueError("Active project changed; import was not applied")
            with self.commit_lock:
                if worker.cancel.is_set():
                    raise runtime.Cancelled("Cancelled before library transaction")
                self.committing = True
            return library.install(plan)

        def done(result):
            self.last_symbol_id = plan["part"].get("symbol", "")
            self.copy_symbol.Enable(bool(self.last_symbol_id))
            self.plan_text.SetValue(
                json.dumps(result, indent=2)
                + "\n\nUse these qualified IDs in KiCad. Refresh the library browser as needed. "
                "Placed symbols/footprints were not updated."
            )
            self.fill_assets()
            self.message("Installed project-local assets and part mapping.")

        self.submit(work, done)

    def on_refresh(self, event=None):
        if not self.working:
            self.load_project()
            self.submit(
                lambda worker: worker.readiness(),
                lambda data: self.message("Runtime readiness: " + str(data)),
            )

    def shutdown(self):
        self.closed = True
        if self.assignment:
            self.assignment.closed = True
        self.catalog_panel.shutdown()
        if self.worker:
            self.worker.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
