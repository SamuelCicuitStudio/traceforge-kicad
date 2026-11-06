"""Manufacturing and project maintenance controls for saved KiCad projects."""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import wx

from . import manufacturing_core as core


class ManufacturingPanel(wx.ScrolledWindow):
    def __init__(self, parent, host, board_file):
        super().__init__(parent)
        self.SetScrollRate(0, 12)
        self.host = host
        self.board_file = Path(board_file).resolve() if board_file else None
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="traceforge-manufacturing"
        )
        self.preview = None
        self.inventory = None
        self.candidates = []
        self.working = False
        if host.dark:
            self.SetBackgroundColour("#222C3A")
            self.SetForegroundColour("#E5EDF8")
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label="Manufacturing & Project Maintenance"), 0, wx.ALL, 9)
        note = wx.StaticText(
            self,
            label=(
                "1. Set up project   2. Enter manufacturer choices   3. "
                "Review checks   4. Generate deliverables"
            ),
        )
        outer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        board_label = self.board_file.stem if self.board_file else "Open a saved PCB in KiCad"
        board_caption = wx.StaticText(self, label=f"Board: {board_label}")
        if self.board_file:
            board_caption.SetToolTip(str(self.board_file))
        outer.Add(board_caption, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(
            wx.StaticText(self, label="Manufacturer"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8
        )
        self.vendor = wx.Choice(self, choices=["PCBWay", "PCBPower"])
        legacy_power = bool(
            self.board_file
            and (self.board_file.parent / "tools" / "export_config_rev_b.json").is_file()
        )
        self.vendor.SetSelection(1 if legacy_power else 0)
        self.vendor.Bind(wx.EVT_CHOICE, self.on_inputs_changed)
        row.Add(self.vendor, 0, wx.RIGHT, 10)
        self.bundle = wx.CheckBox(self, label="Include sibling boards (optional)")
        self.bundle.SetValue(False)
        self.bundle.Bind(wx.EVT_CHECKBOX, self.on_inputs_changed)
        row.Add(self.bundle, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        outer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)

        self.config = wx.TextCtrl(self)
        self.config.Hide()  # Internal profile path; never shown as JSON.
        self.config.Bind(wx.EVT_TEXT, self.on_inputs_changed)
        self.profile_status = wx.StaticText(self, label="Project setup is needed.")
        outer.Add(self.profile_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)

        create_row = wx.BoxSizer(wx.HORIZONTAL)
        for title, action in (
            ("1  Set up project", self.on_setup),
            ("2  Manufacturer choices", self.on_edit_config),
            ("3  Review project", self.on_inspect),
            ("Run KiCad checks", self.on_preflight),
        ):
            button = wx.Button(self, label=title)
            button.Bind(wx.EVT_BUTTON, action)
            create_row.Add(button, 0, wx.RIGHT, 5)
        outer.Add(create_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)

        export_row = wx.BoxSizer(wx.HORIZONTAL)
        for title, action in (
            ("4  Generate new package", self.on_export),
            ("Review existing output", self.on_cleanup_preview),
            ("Rebuild generated package", self.on_replace),
        ):
            button = wx.Button(self, label=title)
            button.Bind(wx.EVT_BUTTON, action)
            export_row.Add(button, 0, wx.RIGHT, 5)
        outer.Add(export_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        library_label = wx.StaticText(self, label="Project-local library table cleanup")
        library_label.SetFont(library_label.GetFont().Bold())
        outer.Add(library_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 7)
        library_row = wx.BoxSizer(wx.HORIZONTAL)
        scan = wx.Button(self, label="Find unused entries")
        scan.Bind(wx.EVT_BUTTON, self.on_library_scan)
        library_row.Add(scan, 0, wx.RIGHT, 6)
        apply = wx.Button(self, label="Remove selected entries (backup first)")
        apply.Bind(wx.EVT_BUTTON, self.on_library_apply)
        library_row.Add(apply)
        outer.Add(library_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 7)
        self.library_list = wx.ListBox(self, style=wx.LB_EXTENDED, size=(-1, 95))
        outer.Add(self.library_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.status = wx.StaticText(self, label="Set up or review this project to begin.")
        outer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 7)
        self.board_table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN, size=(-1, 125))
        for index, (name, width) in enumerate(
            (
                ("Board", 260),
                ("Copper", 75),
                ("Sheets", 70),
                ("Choices", 150),
                ("Package", 185),
                ("Checks", 180),
            )
        ):
            self.board_table.InsertColumn(index, name, width=width)
        outer.Add(self.board_table, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.report = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL, size=(-1, 280)
        )
        self.report.SetFont(
            wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        )
        outer.Add(self.report, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.SetSizer(outer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self._load_existing_profile()
        if self.config.GetValue():
            wx.CallAfter(self.on_inspect)

    def on_destroy(self, event):
        if event.GetEventObject() is self:
            self.executor.shutdown(wait=False, cancel_futures=True)
        event.Skip()

    def manufacturer(self):
        return self.vendor.GetStringSelection().lower()

    def on_inputs_changed(self, event):
        self.preview = None
        if event.GetEventObject() in (self.vendor, self.bundle):
            self._load_existing_profile()
            self.board_table.DeleteAllItems()
            self.report.SetValue(
                "Select Review project to inspect this manufacturer and board scope."
            )
        event.Skip()

    def _load_existing_profile(self):
        path = (
            core.configured_profile(self.board_file, self.manufacturer(), self.bundle.GetValue())
            if self.board_file
            else None
        )
        if path:
            self.config.SetValue(str(path))
            self.profile_status.SetLabel(
                f"Project configured for {self.manufacturer().upper()} "
                f"({'sibling-board bundle' if self.bundle.GetValue() else 'this board only'})."
            )
        else:
            self.config.SetValue("")
            self.profile_status.SetLabel(
                "Project setup is needed for this manufacturer and board scope."
            )

    def config_path(self):
        value = self.config.GetValue().strip()
        if not value:
            raise ValueError(
                "Set up this project for the selected manufacturer and board scope first"
            )
        return Path(value).resolve()

    def display(self, data, summary=None):
        self.report.SetValue(data if isinstance(data, str) else str(data))
        self.status.SetLabel(summary or "Inspection complete. Review unknowns and release holds.")

    def show_board_table(self, preview, checks=None):
        self.board_table.DeleteAllItems()
        boards = preview.get("boards", [preview])
        for index, board in enumerate(boards):
            inventory = board["inventory"]
            output = board["output_state"]
            row = self.board_table.InsertItem(index, Path(board["board"]).stem)
            values = [
                str(len(inventory["copper_layers"])),
                str(len(inventory["sheets"])),
                f"{len(board['quote_unknowns'])} missing"
                if board["quote_unknowns"]
                else "Recorded",
                "Not generated"
                if not output["exists"]
                else "Files intact"
                if output["managed"]
                and not any(
                    output.get(key) for key in ("extra_files", "changed_files", "missing_files")
                )
                else "Review files",
                "Not run",
            ]
            if output["exists"] and output["managed"]:
                release = core.package_release_state(Path(board["output"]), board["quote_unknowns"])
                values[-1] = "HOLD" if release["hold"] else "Export checks passed"
            if checks and index < len(checks):
                result = checks[index]["checks"]
                values[-1] = "HOLD" if result["hold"] else "Checks passed"
            for column, value in enumerate(values, 1):
                self.board_table.SetItem(row, column, value)

    def on_setup(self, _event=None):
        if not self.board_file:
            self.status.SetLabel("Open and save a PCB in KiCad first.")
            return
        existing = core.configured_profile(
            self.board_file, self.manufacturer(), self.bundle.GetValue()
        )
        if existing:
            self._load_existing_profile()
            self.on_inspect()
            return
        vendor = self.manufacturer()
        all_boards = self.bundle.GetValue()
        cli = self._kicad_cli()

        def task():
            return (
                core.create_bundle_starter(self.board_file, vendor, cli)
                if all_boards
                else core.create_starter_config(self.board_file, vendor, cli)
            )

        def done(_path):
            self._load_existing_profile()
            self.status.SetLabel(
                "Project setup saved. Review the board summary and enter verified choices."
            )
            self.on_inspect()

        self._submit(task, done)

    def _submit(self, task, done):
        if self.working:
            return
        self.working = True
        self.status.SetLabel("Working from saved project files…")
        future = self.executor.submit(task)

        def ready(completed):
            try:
                result, error = completed.result(), None
            except Exception as exc:  # show exact deterministic failure, not a guessed remedy
                result, error = None, str(exc)
            wx.CallAfter(self._complete, done, result, error)

        future.add_done_callback(ready)

    def _complete(self, done, result, error):
        if not self:
            return
        self.working = False
        if error:
            self.status.SetLabel(error[:300])
            self.report.SetValue(error)
        else:
            done(result)

    @staticmethod
    def _kicad_cli():
        found = shutil.which("kicad-cli")
        return Path(found) if found else Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")

    def on_edit_config(self, _event=None):
        try:
            path = self.config_path()
            if self.bundle.GetValue():
                manifest = core.load_config(path)
                choices = manifest["board_configs"]
                labels = [Path(item).stem for item in choices]
                with wx.SingleChoiceDialog(
                    self, "Choose the board to configure", "Manufacturer choices", labels
                ) as chooser:
                    if chooser.ShowModal() != wx.ID_OK:
                        return
                    path = (path.parent / choices[chooser.GetSelection()]).resolve()
            config = core.load_config(path)
            expected = core.digest(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.SetLabel(f"Set up the project first: {error}")
            return
        fields = (
            [
                ("assembly_mode", "Assembly sourcing"),
                ("pcb_quantity", "PCB quantity"),
                ("assembled_quantity", "Assembled quantity"),
                ("pcb_type", "PCB type"),
                ("material", "Laminate material"),
                ("finished_thickness_mm", "Finished thickness (mm)"),
                ("finished_outer_copper_oz", "Outer copper (oz)"),
                ("inner_copper_oz", "Inner copper (oz)"),
                ("surface_finish", "Surface finish"),
                ("solder_mask", "Solder mask"),
                ("silkscreen", "Silkscreen"),
                ("controlled_impedance", "Controlled impedance"),
                ("standard_stackup_id", "PCBWay stackup ID"),
                ("stackup_status", "Stackup confirmation"),
                ("inner_residual_copper_percent", "Inner copper remaining (%)"),
                ("special_notes", "Verified order notes"),
            ]
            if self.manufacturer() == "pcbway"
            else [
                ("docs_dir", "CAM and ordering notes folder"),
                ("mechanical_dir", "Reviewed mechanical files folder"),
            ]
        )
        data = config["pcbway"] if self.manufacturer() == "pcbway" else config
        with wx.Dialog(
            self, title=f"Manufacturer choices - {path.stem}", size=(720, 690)
        ) as dialog:
            outer = wx.BoxSizer(wx.VERTICAL)
            outer.Add(
                wx.StaticText(
                    dialog,
                    label=(
                        "Enter only values confirmed by the manufacturer or "
                        "project records. Leave unknown choices blank."
                    ),
                ),
                0,
                wx.ALL,
                10,
            )
            scroller = wx.ScrolledWindow(dialog)
            scroller.SetScrollRate(0, 12)
            grid = wx.FlexGridSizer(cols=2, hgap=12, vgap=8)
            grid.AddGrowableCol(1, 1)
            controls = {}
            for key, label in fields:
                grid.Add(wx.StaticText(scroller, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                raw = data.get(key)
                if key == "assembly_mode":
                    control = wx.Choice(
                        scroller, choices=["Unselected", "turnkey", "partial_turnkey", "consigned"]
                    )
                    control.SetStringSelection(raw if raw else "Unselected")
                elif key == "controlled_impedance":
                    control = wx.Choice(scroller, choices=["Unselected", "Yes", "No"])
                    control.SetStringSelection(
                        "Unselected" if raw is None else "Yes" if raw else "No"
                    )
                elif key == "stackup_status":
                    control = wx.Choice(scroller, choices=["Unselected", "Confirmed by PCBWay"])
                    control.SetSelection(1 if raw == "confirmed" else 0)
                else:
                    shown = (
                        str((path.parent / raw).resolve())
                        if key in ("docs_dir", "mechanical_dir") and raw
                        else ""
                        if raw is None
                        else str(raw)
                    )
                    control = wx.TextCtrl(scroller, value=shown)
                controls[key] = control
                if key in ("docs_dir", "mechanical_dir"):
                    folder_row = wx.BoxSizer(wx.HORIZONTAL)
                    folder_row.Add(control, 1, wx.RIGHT | wx.EXPAND, 5)
                    browse = wx.Button(scroller, label="Browse folder")

                    def choose_folder(_event, target=control):
                        with wx.DirDialog(
                            dialog,
                            "Choose a reviewed source folder",
                            defaultPath=target.GetValue(),
                            style=wx.DD_DIR_MUST_EXIST,
                        ) as picker:
                            if picker.ShowModal() == wx.ID_OK:
                                target.SetValue(picker.GetPath())

                    browse.Bind(wx.EVT_BUTTON, choose_folder)
                    folder_row.Add(browse)
                    grid.Add(folder_row, 1, wx.EXPAND)
                else:
                    grid.Add(control, 1, wx.EXPAND)
            scroller.SetSizer(grid)
            outer.Add(scroller, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
            outer.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 10)
            dialog.SetSizer(outer)
            if dialog.ShowModal() != wx.ID_OK:
                return
            values = {
                key: (
                    control.GetStringSelection()
                    if isinstance(control, wx.Choice)
                    else control.GetValue()
                )
                for key, control in controls.items()
            }
            values = {key: "" if value == "Unselected" else value for key, value in values.items()}
            try:
                core.save_engineering_choices(path, self.manufacturer(), values, expected)
            except (OSError, ValueError) as error:
                self.status.SetLabel(f"Choices not saved: {error}")
                return
        self.preview = None
        self.status.SetLabel("Manufacturer choices saved with a backup. Review the project again.")

    def _preview_args(self):
        return self.bundle.GetValue(), self.manufacturer(), self.config_path()

    def _current_args_match(self, args):
        try:
            return self._preview_args() == args
        except (ValueError, OSError):
            return False

    @staticmethod
    def _preview(args):
        bundle, vendor, path = args
        return core.preview_bundle(vendor, path) if bundle else core.preview_package(vendor, path)

    def on_inspect(self, _event=None):
        try:
            args = self._preview_args()
        except (ValueError, OSError) as error:
            self.status.SetLabel(str(error))
            return

        def done(preview):
            if not self._current_args_match(args):
                return
            self.preview = preview
            self.show_board_table(preview)
            if "boards" in preview:
                summary = (
                    f"{len(preview['boards'])} boards reviewed. Fill missing "
                    f"choices and run KiCad checks."
                )
            else:
                summary = (
                    f"{len(preview['quote_unknowns'])} unknown quote fields; "
                    f"change state: {core.change_state(preview)}"
                )
            self.display(core.engineering_preview(preview), summary)

        self._submit(lambda: self._preview(args), done)

    def on_preflight(self, _event=None):
        try:
            args = self._preview_args()
        except (ValueError, OSError) as error:
            self.status.SetLabel(str(error))
            return

        def task():
            preview = self._preview(args)
            boards = preview.get("boards", [preview])
            results = []
            for board in boards:
                config = core.load_config(Path(board["config"]))
                cli = Path(config.get("kicad_cli", "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"))
                results.append(
                    {"board": board["board"], "checks": core.run_cli_preflight(board, cli)}
                )
            return {"preview": preview, "results": results}

        def done(data):
            if not self._current_args_match(args):
                return
            self.preview = data["preview"]
            self.show_board_table(data["preview"], data["results"])
            self.display(
                core.engineering_preview(data["preview"], data["results"]),
                "KiCad checks complete. Review each board's findings before export.",
            )

        self._submit(task, done)

    def on_cleanup_preview(self, _event=None):
        try:
            args = self._preview_args()
        except (ValueError, OSError) as error:
            self.status.SetLabel(str(error))
            return

        def done(preview):
            if not self._current_args_match(args):
                return
            self.preview = preview
            self.show_board_table(preview)
            self.display(
                core.engineering_preview(preview),
                "Replacement is allowed only for marked generated folders without unmanaged files.",
            )

        self._submit(lambda: self._preview(args), done)

    def _export(self, replace):
        if not self.preview:
            self.status.SetLabel("Inspect and preview before exporting.")
            return
        preview = self.preview
        try:
            if self._preview_args() != (
                "boards" in preview,
                preview["manufacturer"],
                Path(preview.get("manifest", preview.get("config"))),
            ):
                self.status.SetLabel("Manufacturer, mode or config path changed; inspect again.")
                return
        except (ValueError, OSError) as error:
            self.status.SetLabel(str(error))
            return
        if replace:
            states = (
                [preview["output_state"], *[item["output_state"] for item in preview["boards"]]]
                if "boards" in preview
                else [preview["output_state"]]
            )
            if any(
                not state["managed"] or state.get("extra_files") or state.get("changed_files")
                for state in states
            ):
                self.status.SetLabel(
                    "Replacement blocked: unmanaged output files or missing package marker."
                )
                return
            with wx.MessageDialog(
                self,
                f"Rebuild the generated deliverable folder?\n\n{preview['output']}\n\n"
                "The existing generated package will be replaced. Review its files first.",
                "Confirm generated-folder replacement",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            ) as dialog:
                if dialog.ShowModal() != wx.ID_YES:
                    return

        def task():
            return (
                core.export_bundle(preview, replace)
                if "boards" in preview
                else core.export_package(preview, replace)
            )

        def done(result):
            self.preview = None
            lines = [
                f"PACKAGE: {result['output']}",
                (
                    f"STATUS: "
                    f"{'HOLD - review findings' if result['hold'] else 'Export checks passed; CAM approval pending'}"  # noqa: E501 - composed report text or resource path
                ),
                f"EXPORT LOG: {result['log']}",
                "",
            ]
            for reason in result.get("release_reasons", []):
                lines.append("  - " + reason)
            for board in result.get("board_release_states", []):
                lines.append(
                    
                        f"{Path(board['board']).stem}: "
                        f"{'HOLD' if board['hold'] else 'export checks passed'}"
                    
                )
                lines.extend("  - " + reason for reason in board["reasons"])
            self.display(
                "\n".join(lines),
                "Export finished. Manufacturer CAM and assembly approval remain separate.",
            )

        self._submit(task, done)

    def on_export(self, _event=None):
        self._export(False)

    def on_replace(self, _event=None):
        self._export(True)

    def on_library_scan(self, _event=None):
        if not self.board_file:
            self.status.SetLabel("Open a saved PCB first.")
            return

        def done(inventory):
            self.inventory = inventory
            self.candidates = core.library_cleanup_candidates(inventory)
            self.library_list.Set(
                [f"{item['table']}: {item['name']} -> {item['uri']}" for item in self.candidates]
            )
            self.display(
                "Unused project-local library entries:\n"
                + (
                    "\n".join(f"  {item['table']}: {item['name']}" for item in self.candidates)
                    if self.candidates
                    else "  None"
                )
                + "\n\nReview the selected entries before removing them.",
                (
                    f"{len(self.candidates)} unused project-local table "
                    f"entries found. Select only reviewed entries."
                ),
            )

        self._submit(lambda: core.project_inventory(self.board_file), done)

    def on_library_apply(self, _event=None):
        if not self.inventory:
            self.status.SetLabel("Find unused entries first.")
            return
        selected = [self.candidates[index] for index in self.library_list.GetSelections()]
        if not selected or len({item["table"] for item in selected}) != 1:
            self.status.SetLabel("Select one or more entries from the same project-local table.")
            return
        table = selected[0]["table"]
        names = [item["name"] for item in selected]
        path = Path(self.inventory["project"]) / table
        expected = self.inventory["source_hashes"].get(table)
        if not expected:
            self.status.SetLabel("The table was not in the project snapshot; rescan.")
            return
        with wx.MessageDialog(
            self,
            f"Remove these unused entries from {path}?\n\n"
            + "\n".join(names)
            + "\n\nA byte-for-byte backup will be created first.",
            "Confirm library cleanup",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_YES:
                return

        def done(backup):
            self.inventory = None
            self.candidates = []
            self.library_list.Clear()
            self.display(
                "Removed library table entries:\n"
                + "\n".join("  " + name for name in names)
                + f"\n\nBackup saved: {backup}",
                "Project-local table updated. Reopen/rescan KiCad libraries before further edits.",
            )

        self._submit(
            lambda: core.apply_library_cleanup(self.board_file, table, names, expected), done
        )
