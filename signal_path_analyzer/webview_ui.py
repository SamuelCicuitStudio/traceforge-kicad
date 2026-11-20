"""Windows WebView interface and controller for TraceForge tools."""

import csv
from base64 import b64encode
from dataclasses import asdict, replace
import json
import math
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import wx
import wx.html2 as web

from . import __version__
from . import layout_clone_assets as assets
from .cancellation import Cancellation
from .fanout import validate as validate_fanout
from .layout_clone_preview import make_scene
from .traceforge_layout_clone import _validate_snapshot, make_plan, matching_geometry


class WebFrame(wx.Frame):
    def __init__(self, native, tools=None, board_file=None, endpoints=None,
                 native_info=None, components_only=False):
        super().__init__(None, title=f"TraceForge {__version__} — WebView test",
                         size=(1100, 750))
        self.SetMinSize((480, 400))
        self.native = native
        self.native_info = native_info or {}
        self.components_only = components_only
        self.installed_symbol = ""
        self.hotkeys = {}
        self.tools = tools
        self.endpoints = endpoints
        self.endpoint_review = None
        self.manufacturing_preview = None
        self.manufacturing_config = None
        self.library_cleanup = None
        self.footprint_preview = None
        self.board_file = board_file
        self.bom_result = self.bom_cancel = None
        self.bom_proposals = None
        self.bom_replacement = None
        self.catalog = None
        self.catalog_parts = {}
        self.catalog_categories = []
        self.library_stage = self.library_plan = None
        self.visual_nets = {}
        self.visual_focus = {}
        self.visual_focused = False
        self.signal_results = None
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.source = None
        self.via_preview = None
        self.fillet_token = None
        self.text_token = None
        self.cleanup_token = None
        self.via_size_review = None
        self.stitch_scene = self.stitch_review = None
        self.fanout = self.fanout_preview = self.cancel = None
        self.busy = self.closed = False
        self.close_pending = False
        try:
            self.browser = web.WebView.New(self, backend=web.WebViewBackendEdge)
            if not self.browser or not self.browser.AddScriptMessageHandler("traceforge"):
                raise RuntimeError("Could not initialize the TraceForge WebView message bridge.")
        except Exception:
            self.worker.shutdown(wait=False, cancel_futures=True)
            self.Destroy()
            raise
        self.browser.Bind(web.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self.receive)
        self.browser.Bind(web.EVT_WEBVIEW_NAVIGATING, self.navigate)
        self.browser.Bind(web.EVT_WEBVIEW_NEWWINDOW, lambda event: event.Veto())
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.browser, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.page_url = Path(__file__).with_name("webview.html").resolve().as_uri()
        self.browser.Bind(web.EVT_WEBVIEW_LOADED, self.loaded)
        self.browser.LoadURL(self.page_url)
        self.Bind(wx.EVT_HOTKEY, self.on_hotkey)
        from .hub_ui import load_shortcuts

        self.hotkey_conflicts = self.register_hotkeys(load_shortcuts()) if tools else []

    def register_hotkeys(self, shortcuts):
        from .hub_ui import parse_shortcut

        for handle in self.hotkeys:
            self.UnregisterHotKey(handle)
        self.hotkeys.clear()
        failed = []
        for index, (action, shortcut) in enumerate(shortcuts.items()):
            handle = 0xB000 + index
            parsed = parse_shortcut(shortcut) if isinstance(shortcut, str) else None
            if parsed and self.RegisterHotKey(handle, *parsed):
                self.hotkeys[handle] = action
            else:
                failed.append(str(shortcut))
        return failed

    def on_hotkey(self, event):
        action = self.hotkeys.get(event.GetId())
        if action == "toggle_panel":
            self.Show(not self.IsShown())
            if self.IsShown():
                self.Raise()
            return
        mapped = {"highlight_chain": "signals_highlight_chain", "highlight_group": "signals_highlight_group",
                  "clear": "signals_clear", "write_targets": "signals_targets", "export_paths": "signals_export"}
        if action in mapped and not self.busy:
            self.activate_tool("signals.paths")
            self.browser.RunScriptAsync(f"run({json.dumps(mapped[action])});")

    def navigate(self, event):
        if event.GetURL() not in ("about:blank", self.page_url):
            event.Veto()

    def loaded(self, event):
        from .hub_ui import kicad_dark_theme
        from .traceforge_auto_text import TARGET_LAYERS

        self.browser.RunScriptAsync(
            f"document.getElementById('version').textContent = {json.dumps(__version__)};")
        self.browser.RunScriptAsync(f"setTextLayers({json.dumps(TARGET_LAYERS)});")
        dark = kicad_dark_theme()
        self.browser.RunScriptAsync(
            f"document.documentElement.dataset.theme = {json.dumps('dark' if dark else 'light')};")
        logo = Path(__file__).with_name("traceforge-logo.png" if dark else "traceforge-logo-light.png")
        if not logo.is_file():
            logo = Path(__file__).resolve().parents[1] / "icons" / (
                "traceforge-dark-48.png" if dark else "traceforge-light-48.png")
        if logo.is_file():
            encoded = b64encode(logo.read_bytes()).decode("ascii")
            self.browser.RunScriptAsync(f"setLogo({json.dumps('data:image/png;base64,' + encoded)});")
        if self.components_only:
            self.browser.RunScriptAsync(f"configureSchematic({json.dumps(str(self.board_file or ''))});")
        elif getattr(self, "startup_tool", None):
            self.activate_tool(self.startup_tool)
        if self.board_file:
            schematic = str(Path(self.board_file).with_suffix(".kicad_sch"))
            self.browser.RunScriptAsync(f"setBOMSource({json.dumps(schematic)});")

    def close(self, event):
        if self.busy and event.CanVeto():
            event.Veto()
            self.close_pending = True
            self.cancel_operation()
            return
        self.closed = True
        for handle in self.hotkeys:
            self.UnregisterHotKey(handle)
        self.worker.shutdown(wait=False, cancel_futures=True)
        event.Skip()

    def cancel_operation(self):
        if self.cancel:
            self.cancel.cancel()
        if self.bom_cancel:
            self.bom_cancel.set()

    def activate_tool(self, tool):
        self.startup_tool = tool
        self.browser.RunScriptAsync(
            f"typeof activate === 'function' && activate({json.dumps(tool)});")

    def receive(self, event):
        if self.closed:
            return
        try:
            request = json.loads(event.GetString())
            action = request["action"]
            if action == "cancel":
                self.cancel_operation()
                return
            if self.busy:
                return
            if action in ("settings_runtime_load", "settings_runtime_save"):
                from . import component_runtime

                keys = ("browser", "node", "helpers", "python")
                values = component_runtime.settings()
                if action == "settings_runtime_save":
                    values.update({key: request["runtime"][key].strip() for key in keys})
                    component_runtime.save_settings(values)
                self.send(dict(runtime_settings={key: values[key] for key in keys},
                               message=("Component runtime paths saved." if action.endswith("_save")
                                        else "Component runtime settings loaded.")))
                return
            if self.components_only and not action.startswith(("catalog_", "library_", "settings_")):
                raise ValueError("This launcher supports schematic component research and library import.")
            if action == "library_choose_project" and self.components_only:
                with wx.FileDialog(self, "Choose KiCad schematic or project",
                                   wildcard="KiCad designs|*.kicad_sch;*.kicad_pro;*.kicad_pcb",
                                   style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                    if dialog.ShowModal() == wx.ID_OK:
                        self.board_file = dialog.GetPath()
                        self.library_stage = self.library_plan = None
                        self.installed_symbol = ""
                        self.send(dict(schematic_project=self.board_file, message="Project selected."))
                return
            if action == "library_copy_symbol":
                if self.installed_symbol and wx.TheClipboard.Open():
                    try:
                        wx.TheClipboard.SetData(wx.TextDataObject(self.installed_symbol))
                    finally:
                        wx.TheClipboard.Close()
                    self.send(dict(message="Copied symbol ID. Search for it in KiCad’s symbol chooser."))
                return
            if action in ("clone_template_load", "clone_template_save"):
                self.clone_template(action)
                return
            if action in ("settings_load", "settings_save"):
                from .hub_ui import LABELS, load_shortcuts, parse_shortcut, save_shortcuts

                shortcuts = load_shortcuts()
                if action == "settings_save":
                    shortcuts = {key: request["shortcuts"][key].strip() for key in LABELS}
                    parsed = [parse_shortcut(value) for value in shortcuts.values()]
                    if None in parsed or len(set(parsed)) != len(parsed):
                        raise ValueError("Use a unique valid shortcut with a modifier for each action.")
                    save_shortcuts(shortcuts)
                    if not self.components_only:
                        self.hotkey_conflicts = self.register_hotkeys(shortcuts)
                info = self.native_info
                self.send(dict(settings=dict(shortcuts=shortcuts, labels=LABELS, conflicts=self.hotkey_conflicts,
                                             helper=info.get("traceforge_version"), board=self.board_file,
                                             python=sys.version.split()[0]), message="TraceForge settings loaded."))
                return
            if action == "bom_cancel_replacement":
                self.bom_replacement = None
                self.send({"replacement_closed": True, "message": "Returned to BOM Cost."})
                return
            if action == "bom_browse":
                with wx.FileDialog(self, "Choose root schematic",
                                   wildcard="KiCad schematic (*.kicad_sch)|*.kicad_sch",
                                   style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                    if dialog.ShowModal() == wx.ID_OK:
                        self.send({"schematic": dialog.GetPath(), "message": "Root schematic selected."})
                return
            if action == "bom_export":
                self.export_bom()
                return
            if action == "catalog_datasheet":
                part = self.catalog_parts.get(request["code"])
                if part and part.datasheet_url.startswith("https://"):
                    wx.LaunchDefaultBrowser(part.datasheet_url)
                return
            if action not in ("record", "preview", "apply", "grid",
                              "gaps_scan", "gaps_focus", "gaps_clear",
                              "array_preview", "array_apply", "fanout_analyze",
                              "fanout_preview", "fanout_apply", "fanout_remove",
                              "fanout_suggest", "signals_refresh", "signals_focus", "signals_focus_groups",
                              "signals_clear", "signals_zoom", "signals_targets",
                              "signals_highlight_chain", "signals_highlight_group",
                              "signals_export", "fillet_preview", "fillet_apply",
                              "signals_chains_load", "signals_chains_save", "signals_chains_find",
                              "signals_endpoint_detect", "signals_endpoint_pick",
                              "signals_endpoint_choose", "signals_endpoint_add", "signals_chain_selection",
                              "fillet_restore", "rotate_apply",
                              "text_layout_preview", "text_layout_apply",
                              "via_pad_scan", "via_pad_focus", "cleanup_scan",
                              "cleanup_highlight", "cleanup_remove",
                              "teardrop_apply", "teardrop_advanced",
                              "via_size_inventory", "via_size_select", "via_size_preview",
                              "via_size_review_delete", "via_size_apply", "via_size_delete",
                              "stitch_load", "stitch_path", "stitch_preview", "stitch_apply",
                              "stitch_select", "stitch_remove", "bom_calculate", "bom_focus", "bom_review", "bom_apply",
                              "visual_refresh", "visual_edit", "visual_focus",
                              "catalog_categories", "catalog_search", "catalog_details",
                              "catalog_check_cad", "catalog_verify_step", "library_inventory",
                              "catalog_replacement", "catalog_assign",
                              "manufacturing_setup", "manufacturing_inspect", "manufacturing_preflight",
                              "manufacturing_read_config", "manufacturing_save_config", "manufacturing_export",
                              "manufacturing_library_scan", "manufacturing_library_remove",
                              "footprints_preview", "footprints_apply",
                              "library_stage", "library_preview", "library_plan", "library_install"):
                raise ValueError("Unknown WebView action.")
        except (OSError, TypeError, ValueError, KeyError) as exc:
            self.send({"error": str(exc)})
            return
        self.busy = True
        if action in ("bom_calculate", "bom_review", "bom_apply", "library_stage", "library_preview") or action.startswith("catalog_"):
            self.bom_cancel = threading.Event()
        if action in ("manufacturing_inspect", "manufacturing_preflight"):
            self.bom_cancel = threading.Event()
        if action in ("fanout_preview", "cleanup_scan", "via_size_preview", "stitch_preview"):
            self.cancel = Cancellation()
        future = self.worker.submit(self.run_action, action, request)
        future.add_done_callback(lambda result: wx.CallAfter(self.finish, result))

    def send(self, value):
        if not self.closed:
            self.browser.RunScriptAsync(f"receive({json.dumps(value, ensure_ascii=True)});")

    def finish(self, future):
        if self.closed:
            return
        self.busy = False
        cancel, self.cancel = self.cancel, None
        bom_cancel, self.bom_cancel = self.bom_cancel, None
        try:
            if bom_cancel and bom_cancel.is_set() and not getattr(self, "bom_committed", False):
                self.send({"error": "Operation cancelled."})
                return
            if cancel and cancel.cancelled:
                self.fanout_preview = None
                self.cleanup_token = None
                self.via_size_review = None
                self.stitch_review = None
                self.send({"error": "Scan or preview cancelled."})
                return
            self.send(future.result())
        except Exception as exc:
            self.send({"error": str(exc)})
        finally:
            self.bom_committed = False
            if cancel:
                cancel.close()
            if self.close_pending:
                wx.CallAfter(self.Close)

    def run_action(self, action, request):
        if action == "footprints_preview":
            self.footprint_preview = None
            models = request.get("models") is True
            result = self.native("component_update_preview", library_models=models)
            if result["ready"]:
                self.footprint_preview = (models, result["token"])
            return dict(footprints=result, message="Footprint comparison ready.")
        if action == "footprints_apply":
            reviewed, self.footprint_preview = self.footprint_preview, None
            if not reviewed or reviewed[0] != (request.get("models") is True):
                raise ValueError("Preview the selected footprints with the current model policy.")
            result = self.native("component_update_apply", token=reviewed[1])
            self.signal_results = None
            return dict(message="Updated " + ", ".join(result["updated"]) + ". " + result["note"])
        if action.startswith("manufacturing_"):
            return self.run_manufacturing(action, request)
        if action == "catalog_replacement":
            return self.prepare_replacement(request)
        if action == "catalog_assign":
            return self.assign_catalog_part(request)
        if action == "bom_apply":
            return self.apply_bom(request)
        if action == "bom_review":
            return self.review_bom(request)
        if action == "bom_focus":
            return self.focus_bom_row(int(request["row"]))
        if action.startswith("library_"):
            return self.run_library(action, request)
        if action.startswith("catalog_"):
            return self.run_catalog(action, request)
        if action.startswith("visual_"):
            return self.run_visual(action, request)
        if action == "bom_calculate":
            return self.calculate_bom(request)
        if action.startswith("stitch_"):
            return self.run_stitch(action, request)
        if action.startswith("via_size_"):
            return self.run_via_size(action, request)
        if action == "teardrop_advanced":
            self.native("visual_teardrops")
            return dict(message="Opened KiCad’s Edit Teardrops dialog.")
        if action == "teardrop_apply":
            result = self.native(action, settings=request["settings"])
            token = result["token"]
            deadline = time.monotonic() + 45
            while result["state"] == "running" and time.monotonic() < deadline:
                time.sleep(.25)
                result = self.native("teardrop_status", token=token)
            if result["state"] == "running":
                raise TimeoutError("KiCad is still processing teardrops. Check PCB Editor.")
            if result["state"] != "complete":
                raise RuntimeError(result["message"])
            return dict(message=result["message"])
        if action == "cleanup_scan":
            self.cleanup_token = None
            result = self.native(action, net=str(request.get("net", "")),
                                 cancel_file=self.cancel.path)
            self.cleanup_token = result["token"]
            return dict(cleanup=result, message=f"Scanned {result['scanned']} tracks.")
        if action in ("cleanup_highlight", "cleanup_remove"):
            if not self.cleanup_token:
                raise ValueError("Scan tracks before reviewing or applying cleanup.")
            ids = request["ids"]
            if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
                raise ValueError("Choose findings from the scan.")
            token = self.cleanup_token
            if action == "cleanup_remove":
                self.cleanup_token = None
            result = self.native(action, token=token, ids=ids)
            if action == "cleanup_highlight":
                return dict(message=f"Highlighted {result.get('highlighted', 0)} tracks.")
            return dict(cleanup_applied=True, message=f"Removed {result['removed']} tracks "
                        f"and fused {result['fused']} groups. KiCad Undo is available.")
        if action == "via_pad_scan":
            result = self.native("via_manage_pad_scan")
            return dict(via_pad=result["vias"], message=f"{result['count']} vias touching pads.")
        if action == "via_pad_focus":
            ids = request["ids"]
            if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
                raise ValueError("Choose a via or contact group from the scan.")
            result = self.native("via_manage_focus", ids=ids, fast=True)
            return dict(message=f"Focused {result['count']} vias in KiCad.")
        if action == "rotate_apply":
            result = self.native(action, angle=request["angle"])
            return dict(message=f"Rotated {result['components']} footprints "
                                f"by {result['angle']:g}°. KiCad Undo is available.")
        if action.startswith("text_layout_"):
            return self.run_text_layout(action, request)
        if action.startswith("fillet_"):
            return self.run_fillet(action, request)
        if action.startswith("signals_"):
            return self.run_signals(action, request)
        if action.startswith("fanout_"):
            return self.run_fanout(action, request)
        if action == "gaps_scan":
            result = self.native("unrouted_scan")
            return dict(gaps=result["rows"], gap_summary=dict(nets=result.get("nets", 0),
                        native_airwires=result.get("native_airwires")),
                        message=f"{len(result['rows'])} gaps in {result.get('nets', 0)} nets.")
        if action == "gaps_focus":
            result = self.native("unrouted_focus", id=str(request["id"]),
                                 whole_net=request.get("whole_net") is True)
            if result.get("resolved"):
                return self.run_action("gaps_scan", {})
            return dict(focused_gap=request["id"], message="Zoomed to gap." if result.get("zoomed")
                        else "Endpoints highlighted.")
        if action == "gaps_clear":
            self.native("unrouted_clear")
            return dict(focused_gap=None, message="Highlight cleared.")
        if action == "array_preview":
            self.via_preview = None
            axis = request.get("axis", "auto")
            if axis not in ("auto", "columns", "rows"):
                raise ValueError("Invalid via array axis.")
            result = self.native("via_array_preview", fixed_axis=axis,
                                 fixed_count=int(request.get("count", 1)),
                                 ignore_drc=request.get("ignore_drc") is True)
            self.via_preview = result["token"] if result["accepted"] else None
            return dict(array=result, message="Array preview ready."
                        if result["accepted"] else "Via array is blocked.")
        if action == "array_apply":
            if not self.via_preview:
                raise ValueError("Preview an accepted via array first.")
            token, self.via_preview = self.via_preview, None
            result = self.native("via_array_apply", token=token)
            return dict(message=result["message"], array_applied=True)
        return self.run_clone(action, request)

    def run_manufacturing(self, action, request):
        from . import manufacturing_core as core

        if not self.board_file:
            raise ValueError("Choose a saved KiCad design first.")
        board = Path(self.board_file).resolve()
        vendor, bundle = request["vendor"], request.get("bundle") is True
        if vendor not in ("pcbway", "pcbpower"):
            raise ValueError("Choose PCBWay or PCBPower.")
        active = Path(self.native("info")["board"]).resolve()
        if active != board:
            raise ValueError("The active PCB changed. Reopen TraceForge.")
        if action == "manufacturing_library_scan":
            self.library_cleanup = None
            inventory = core.project_inventory(board)
            candidates = core.library_cleanup_candidates(inventory)
            self.library_cleanup = (board, inventory["source_hashes"], candidates)
            return dict(cleanup_libraries=candidates,
                        message=f"Found {len(candidates)} unused project-local entries.")
        if action == "manufacturing_library_remove":
            reviewed = self.library_cleanup
            if not reviewed or reviewed[0] != board:
                raise ValueError("Scan the active project's libraries first.")
            _, hashes, candidates = reviewed
            indices = request.get("indices")
            if not isinstance(indices, list) or not indices or any(
                type(index) is not int or not 0 <= index < len(candidates) for index in indices
            ):
                raise ValueError("Check the entries to remove.")
            selected = [candidates[index] for index in dict.fromkeys(indices)]
            table = selected[0]["table"]
            if any(item["table"] != table for item in selected) or not hashes.get(table):
                raise ValueError("Choose reviewed entries from a single project-local table.")
            names = [item["name"] for item in selected]
            backup = core.apply_library_cleanup(board, table, names, hashes[table])
            self.library_cleanup = self.manufacturing_preview = None
            return dict(cleanup_libraries=[], cleanup_backup=str(backup),
                        message=f"Removed {len(names)} table entries. Backup saved.")
        profile = core.configured_profile(board, vendor, bundle)
        if not profile and action == "manufacturing_setup":
            cli = Path(shutil.which("kicad-cli") or Path(sys.executable).with_name("kicad-cli.exe"))
            creator = core.create_bundle_starter if bundle else core.create_starter_config
            profile = creator(board, vendor, cli)
        if not profile:
            raise ValueError("Set up the project for this manufacturer and board scope first.")
        key = (vendor, bundle, profile)
        choices = core.load_config(profile)["board_configs"] if bundle else []
        config_path = profile
        if bundle and action in ("manufacturing_read_config", "manufacturing_save_config"):
            choice = request.get("board_config")
            if choice not in choices:
                return dict(manufacturing_choices=choices, message="Choose a board configuration to edit.")
            config_path = (profile.parent / choice).resolve()
        config_key = (*key, config_path)
        if action == "manufacturing_read_config":
            self.manufacturing_config = (config_key, core.digest(config_path))
            return dict(manufacturing_config=config_path.read_text(encoding="utf-8"),
                        manufacturing_choices=choices, message=f"Loaded {config_path.name}.")
        if action == "manufacturing_save_config":
            if self.manufacturing_config is None or self.manufacturing_config[0] != config_key:
                raise ValueError("Load the current configuration before editing it.")
            core.save_reviewed_config(config_path, request["config"], self.manufacturing_config[1], vendor)
            self.manufacturing_config = (config_key, core.digest(config_path))
            self.manufacturing_preview = None
            return dict(message=f"Saved {profile.name}. Review the project again.")
        if action == "manufacturing_export":
            reviewed = self.manufacturing_preview
            if not reviewed or reviewed[0] != key:
                raise ValueError("Review the current project and board scope before export.")
            preview = reviewed[1]
            self.manufacturing_preview = None
            export = core.export_bundle if bundle else core.export_package
            result = export(preview, request["replace"] is True)
            integrity = ([item["output_integrity"] for item in result.get("board_release_states", [])]
                         if bundle else [result.get("output_integrity", {})])
            held_package = (result.get("exit_code") == 2 and result["hold"]
                            and integrity and all(
                                state.get("managed") and not any(state.get(key) for key in
                                    ("missing_files", "extra_files", "changed_files"))
                                for state in integrity))
            if result.get("exit_code") and not held_package:
                raise RuntimeError(f"Manufacturing export failed (exit {result['exit_code']}). "
                                   f"Review the exporter log at {result['log']}.")
            lines = [f"Package: {result['output']}", f"Log: {result['log']}"]
            lines.extend(result.get("release_reasons", []))
            for item in result.get("board_release_states", []):
                lines.extend([Path(item["board"]).stem, *item["reasons"]])
            status = "Export finished with release holds." if result["hold"] else "Export checks passed."
            return dict(manufacturing_report="\n".join(lines), message=status)
        self.manufacturing_preview = None
        with core.cancel_scope(self.bom_cancel or threading.Event()):
            preview = (core.preview_bundle if bundle else core.preview_package)(vendor, profile)
            checks = None
            if action == "manufacturing_preflight":
                checks = []
                for item in preview.get("boards", [preview]):
                    config = core.load_config(Path(item["config"]))
                    cli = Path(config.get("kicad_cli", "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"))
                    checks.append(dict(board=item["board"], checks=core.run_cli_preflight(item, cli)))
        self.manufacturing_preview = (key, preview)
        states = [preview["output_state"], *(item["output_state"] for item in preview.get("boards", []))]
        can_replace = all(state["exists"] and state["managed"]
                          and not state.get("extra_files") and not state.get("changed_files")
                          for state in states)
        return dict(manufacturing_report=core.engineering_preview(preview, checks),
                    manufacturing_choices=choices,
                    manufacturing_ready=dict(output=preview["output"], replace=can_replace,
                                             create=not preview["output_state"]["exists"]),
                    message="KiCad checks completed." if checks is not None else "Project review ready.")

    def prepare_replacement(self, request):
        from . import component_occurrences, lcsc_research_backend as api, replacement_search
        from .combined_research import CombinedBackend

        self.bom_replacement = None
        index = int(request["row"])
        report = self.bom_result
        if not report or not 0 <= index < len(report["lines"]):
            raise ValueError("Choose a BOM row first.")
        row = report["lines"][index]
        expected = component_occurrences.expand(report["source_parts"], set(row["references"]))
        if not expected:
            raise ValueError("Recalculate the BOM to capture component information.")
        if self.catalog is None:
            self.catalog = CombinedBackend()
        cancel = self.bom_cancel
        filters, unresolved, category = {}, [], None
        replace_part = request.get("replacement") is True
        keyword = row.get("mpn") or row.get("lcsc") or ""
        if replace_part:
            supplier = None
            if row.get("lcsc"):
                try:
                    part = self.catalog.exact(row["lcsc"], cancel)
                    if not row.get("mpn") or part.mpn.casefold() == row["mpn"].casefold():
                        supplier = part
                except api.Cancelled:
                    raise
                except api.LCSCError:
                    pass
            settings = replacement_search.current_settings(expected, supplier)
            self.catalog_categories, *_ = self.catalog.categories(cancel)
            category = replacement_search.find_category(
                self.catalog_categories, settings["kind"], settings["category_hint"])
            query = api.Query(in_stock=True, category_id=category.id if category else None,
                              category_ids=api.category_leaves(self.catalog_categories, category.id) if category else ())
            groups, *_ = self.catalog.filter_groups(query, cancel)
            filters, _, unresolved = replacement_search.choose_filters(groups, settings)
            keyword = ""
        if cancel.is_set():
            raise api.Cancelled("Replacement search cancelled.")
        self.catalog_parts = {}
        self.bom_replacement = (report, expected)
        return dict(replacement=dict(references=[part["reference"] for part in expected],
                                     value=expected[0].get("value"), footprint=expected[0].get("footprint"),
                                     keyword=keyword, stock=replace_part, filters=filters,
                                     category=category.id if category else None),
                    catalog_categories=[asdict(item) for item in self.catalog_categories],
                    message=("Review filters for: " + ", ".join(unresolved)) if unresolved else
                    "Select the part to assign to the listed references.")

    def assign_catalog_part(self, request):
        from . import bom_cost, component_info

        report, expected = self.bom_replacement or (None, None)
        if not report or report is not self.bom_result:
            raise ValueError("Start assignment from the current BOM.")
        part = self.catalog_parts.get(request["code"])
        if part is None:
            raise ValueError("Select a part from the current results.")
        schematic = report.get("schematic")
        if not schematic and self.board_file:
            schematic = Path(self.board_file).with_suffix(".kicad_sch")
        if not schematic or not Path(schematic).is_file():
            raise ValueError("Choose the saved root schematic in BOM Cost.")
        cancel = self.bom_cancel
        checked = self.catalog.details(part, cancel)
        if (checked.code, checked.mpn) != (part.code, part.mpn):
            raise ValueError("Supplier identity changed. Search again.")
        component_info.validate_passive(expected, checked)
        props = component_info.selected_properties(checked, Path(schematic).parent)
        refs = self.write_bom_assignment(schematic, expected, props, cancel)
        self.bom_committed = True
        self.bom_replacement = self.bom_proposals = self.bom_result = None
        self.bom_result = bom_cost.update_assignments(report, [(refs, props)], threading.Event())
        return dict(bom=self.bom_snapshot(), replacement_closed=True,
                    message=f"Assigned {checked.code} to {len(refs)} references.")

    def review_bom(self, request):
        from . import bom_mpn_assignment, bom_optimizer
        from .combined_research import CombinedBackend

        self.bom_proposals = None
        if not self.bom_result:
            raise ValueError("Calculate the BOM before reviewing assembly stock or assignments.")
        mode = request["review_mode"]
        if mode not in ("assembly", "optimize", "passives", "mpn"):
            raise ValueError("Choose a BOM review.")
        cancel = self.bom_cancel
        backend = CombinedBackend()

        def progress(index, count, refs):
            if not cancel.is_set():
                wx.CallAfter(self.bom_progress, cancel, f"Checking {index}/{count}: {refs}")

        params = None
        if mode == "mpn":
            result = bom_mpn_assignment.scan(self.bom_result, backend, cancel, progress,
                                             request["identity_source"])
        else:
            params = bom_optimizer.Parameters(request["scope"], request["tolerance"],
                                               request["stock"] is True, request["dielectric"] is True,
                                               library_tier="all" if mode == "passives" else "basic")
            result = bom_optimizer.scan(self.bom_result, backend, params, cancel, progress,
                                        optimize=mode != "assembly")
        observations = self.bom_result.setdefault("assembly_observations", {})
        for code, part in result["observations"].items():
            observations[code] = dict(tier=part.assembly_tier, stock=part.assembly_stock,
                                      prices=part.assembly_prices, observed_at=part.assembly_observed_at,
                                      source=part.assembly_source)
        rows = []
        self.bom_proposals = (self.bom_result, result["proposals"], mode, params)
        for index, proposal in enumerate(result["proposals"]):
            candidate = proposal.get("candidate")
            rows.append(dict(index=index if candidate else None, references=proposal["row"]["references"],
                             code=proposal["row"].get("lcsc"),
                             candidate=f"{candidate.code} / {candidate.mpn}" if candidate else "",
                             reason=proposal["reason"], before=str(proposal.get("before") or ""),
                             after=str(proposal.get("after") or "")))
        if mode == "assembly":
            for line in self.bom_result["lines"]:
                item = observations.get(line["lcsc"], {})
                stock = item.get("stock")
                rows.append(dict(references=line["references"], code=line["lcsc"], stock=stock,
                                 tier=item.get("tier", "Unknown"), reason=item.get("source", "Unknown")))
        return dict(bom_review=rows, message=f"BOM review complete. {len(rows)} rows.")

    def apply_bom(self, request):
        from . import bom_cost, bom_mpn_assignment, bom_optimizer, component_info
        from . import component_occurrences, supplier_records
        from .combined_research import CombinedBackend

        report, proposals, mode, params = self.bom_proposals or (None, [], None, None)
        if not report or report is not self.bom_result:
            raise ValueError("Scan the current BOM before applying assignments.")
        indices = request.get("indices", [])
        if not indices or any(type(index) is not int or not 0 <= index < len(proposals)
                              or not proposals[index].get("candidate") for index in indices):
            raise ValueError("Check one or more available proposals.")
        schematic = report.get("schematic")
        if not schematic and self.board_file:
            schematic = Path(self.board_file).with_suffix(".kicad_sch")
        if not schematic or not Path(schematic).is_file():
            raise ValueError("Choose the saved root schematic before applying assignments.")
        chosen = [proposals[index] for index in dict.fromkeys(indices)]
        removed = {ref for proposal in chosen for ref in proposal["row"]["references"]}
        orders = {}
        if mode != "mpn":
            for proposal in chosen:
                candidate = proposal["candidate"]
                code = candidate.code
                per_board = sum(len(p["row"]["references"]) for p in chosen if p["candidate"].code == code)
                per_board += sum(len(set(row["references"]) - removed)
                                 for row in report["lines"] if row["lcsc"] == code)
                demand = math.ceil(per_board * report["boards"] * (1 + report["spares_percent"] / 100))
                _, order = bom_optimizer.assembly_cost(candidate, demand)
                if order is None or (params.require_stock and (candidate.assembly_stock or 0) < order):
                    raise ValueError(f"{code}: insufficient stock for the combined selected quantity.")
                orders[code] = order
        backend = CombinedBackend()
        cancel, changes, updated, error = self.bom_cancel, [], set(), ""
        self.bom_proposals = None
        for proposal in chosen:
            if cancel.is_set():
                break
            references = proposal["row"]["references"]
            if set(references) <= updated:
                continue
            expected = component_occurrences.expand(report["source_parts"], set(references))
            if updated & {part["reference"] for part in expected}:
                error = "Selected proposals overlap. Review the updated BOM before continuing."
                break
            try:
                candidate = proposal["candidate"]
                wx.CallAfter(self.bom_progress, cancel, "Updating " + ", ".join(references))
                checked = (supplier_records.refresh_saved(candidate, expected)
                           if candidate.verification_source == "saved project information"
                           else backend.details(candidate, cancel))
                if (checked.code, checked.mpn) != (candidate.code, candidate.mpn):
                    raise ValueError("Supplier identity changed. Scan again.")
                component_info.validate_passive(expected, checked)
                if mode == "mpn":
                    bom_mpn_assignment.validate(proposal["parts"], checked)
                else:
                    assembly = backend.assembly.exact(checked.code, cancel)
                    if (params.library_tier == "basic" and assembly.assembly_tier != "Basic"
                            or params.require_stock and (assembly.stock or 0) < orders[checked.code]):
                        raise ValueError("Assembly class or stock changed. Scan again.")
                    issues = bom_optimizer.compatible(proposal["settings"], checked, params)
                    if issues:
                        raise ValueError("; ".join(issues))
                props = component_info.selected_properties(checked, Path(schematic).parent)
                if all(component_info.schema.properties(part.get("properties", {})).get("MPN", "").casefold()
                       == checked.mpn.casefold() for part in expected):
                    prior = component_info.schema.properties(expected[0].get("properties", {}))
                    props = {key: value or prior.get(key, "") for key, value in props.items()}
                refs = self.write_bom_assignment(schematic, expected, props, cancel)
                changes.append((refs, props))
                updated.update(refs)
            except Exception as exc:
                error = str(exc)
                break
        if not changes and error:
            raise ValueError(error)
        if changes:
            self.bom_committed = True
            self.bom_result = None
            self.bom_result = bom_cost.update_assignments(report, changes, threading.Event())
        status = f"Updated {len(updated)} references."
        if error or cancel.is_set():
            status += " " + (error or "Cancelled remaining assignments.")
        return dict(bom=self.bom_snapshot(), message=status)

    def write_bom_assignment(self, schematic, expected, props, cancel):
        from . import component_info

        refs = sorted(part["reference"] for part in expected)
        board = Path(self.native("info")["board"]).resolve()
        if (not refs or board.parent != Path(schematic).resolve().parent
                or (self.board_file and board != Path(self.board_file).resolve())):
            raise ValueError("The references or schematic do not match the active PCB project.")
        token = self.native("component_info_preview", refs=refs, properties=props, expected=expected)["token"]
        plan = component_info.plan(schematic, expected, props, cancel=cancel)
        if cancel.is_set():
            raise ValueError("Assignment cancelled before saving.")
        journal = component_info.install(plan)["journal"]
        try:
            self.native("component_info_apply", token=token)
        except Exception as apply_error:
            try:
                component_info.rollback(plan, journal)
            except Exception as rollback_error:
                raise RuntimeError(f"PCB update failed: {apply_error}. Schematic rollback failed: "
                                   f"{rollback_error}. Recovery journal: {journal}") from rollback_error
            raise
        return refs

    def focus_bom_row(self, index):
        if not self.bom_result or not 0 <= index < len(self.bom_result["lines"]):
            raise ValueError("Select a row from the calculated BOM.")
        board = Path(self.native("info")["board"]).resolve()
        root = self.bom_result.get("schematic")
        if (self.board_file and board != Path(self.board_file).resolve()
                or root and board.parent != Path(root).resolve().parent):
            raise ValueError("The BOM belongs to another PCB project.")
        refs = list(dict.fromkeys(self.bom_result["lines"][index]["references"]))
        highlighted = self.native("highlight", nets=[], refs=refs, zoom=True)
        if highlighted != len(refs):
            self.native("clear")
            raise ValueError("Some BOM references are missing from the active PCB.")
        zoomed = self.native("zoom")
        detail = " Zoomed to the selection." if zoomed else " PCB Editor could not zoom to the selection."
        return dict(message="Highlighted " + ", ".join(refs) + "." + detail)

    def run_library(self, action, request):
        from . import component_library as library
        from .component_runtime import Worker

        if not self.board_file:
            raise ValueError("Open a saved PCB project first.")
        project = library.discover(self.board_file)
        if action == "library_inventory":
            symbols = [dict(nickname=item["nickname"], assets=library.symbol_names(item["path"]))
                       for item in project["symbols"]]
            footprints = [dict(nickname=item["nickname"], assets=library.footprint_names(item["path"]))
                          for item in project["footprints"]]
            return dict(library_inventory=dict(symbols=symbols, footprints=footprints,
                        symbol=project["symbol"], footprint=project["footprint"]),
                        message="Project libraries loaded.")
        if action == "library_stage":
            self.library_stage = self.library_plan = None
            worker = Worker()
            worker.cancel = self.bom_cancel
            mode = request["mode"]
            if request["category"] != "custom":
                mode = "none" if request["reuse_footprint"] else "footprint"
            self.library_stage = worker.stage(project["root"], request["lcsc"], request["mpn"],
                                              mode, request["step"] is True)
            return dict(library_stage=self.library_stage, message="CAD downloads staged for review.")
        if action == "library_preview":
            from .component_runtime import export_cad_previews

            if not self.library_stage:
                raise ValueError("Stage assets before previewing them.")
            worker = Worker()
            worker.cancel = self.bom_cancel
            paths = export_cad_previews(worker, self.library_stage)
            previews = [dict(name=path.stem, svg=b64encode(path.read_bytes()).decode("ascii"))
                        for path in paths]
            return dict(library_preview=previews, message=f"{len(previews)} CAD previews available.")
        if action == "library_install":
            plan, self.library_plan = self.library_plan, None
            if not plan:
                raise ValueError("Build and review an import plan first.")
            if self.native:
                active = self.native("info")["board"]
                if Path(active).resolve() != Path(self.board_file).resolve():
                    raise ValueError("The active PCB changed. Build a new import plan.")
            library.install(plan)
            self.installed_symbol = plan["part"].get("symbol", "")
            return dict(library_symbol=self.installed_symbol,
                        message="Installed the reviewed assets in the project libraries.")
        self.library_plan = None
        if request["reviewed"] is not True:
            raise ValueError("Review the package and pin-to-pad mapping before planning the import.")
        sym = next((item for item in project["symbols"] if item["nickname"] == request["symbol_library"]), None)
        fp = next((item for item in project["footprints"] if item["nickname"] == request["footprint_library"]), None)
        if not sym or not fp:
            raise ValueError("Select the destination symbol and footprint libraries.")
        part = {key: request.get(key, "").strip() for key in
                ("lcsc", "mpn", "manufacturer", "description", "package", "datasheet",
                 "value", "tolerance", "voltage", "power", "dielectric")}
        source = self.library_stage or {}
        if source and (source["mpn"] != part["mpn"] or source["lcsc"] != part["lcsc"].upper()):
            raise ValueError("The selected identity changed. Stage the exact part again.")
        part.update(provenance=source.get("source", {}), package_pin_map_reviewed=True)
        model = None
        if source.get("model") and request["step"]:
            model = dict(path=source["model"], checked=request["model_reviewed"] is True,
                         offset=[request[key] for key in ("ox", "oy", "oz")],
                         rotation=[request[key] for key in ("rx", "ry", "rz")])
        self.library_plan = library.plan_import(
            project["root"], part, sym, fp, candidate_symbol=source.get("symbol"),
            candidate_footprint=source.get("footprint"), reuse_symbol=request["reuse_symbol"],
            reuse_footprint=request["reuse_footprint"], category=request["category"],
            model=model, placement_symbol=True)
        return dict(library_plan=dict(summary=self.library_plan["summary"],
                                      files=list(self.library_plan["writes"])),
                    message="Import plan ready for review.")

    def run_catalog(self, action, request):
        from . import lcsc_research_backend as api
        from .combined_research import CombinedBackend
        from .jlc_research_backend import JLCError

        if self.catalog is None:
            self.catalog = CombinedBackend()
        cancel = self.bom_cancel
        if action == "catalog_categories":
            self.catalog_categories, *_ = self.catalog.categories(cancel)
            return dict(catalog_categories=[asdict(item) for item in self.catalog_categories],
                        message="Catalog categories loaded.")
        if action == "catalog_search":
            keyword = request["keyword"].strip()
            category = int(request["category"]) if request.get("category") else None
            tier = request["tier"]
            if tier not in ("all", "basic", "extended", "preferred"):
                raise ValueError("Choose a valid assembly class.")
            filters = request["filters"]
            if (not keyword and category is None and tier == "all"
                    and request["assembly_stock"] is not True):
                self.catalog_categories, *_ = self.catalog.categories(cancel)
                return dict(catalog_categories=[asdict(item) for item in self.catalog_categories],
                            message="Choose a category or enter a keyword, MPN, or LCSC code.")
            if api.C_RE.fullmatch(keyword):
                category, filters = None, {}
            leaves = api.category_leaves(self.catalog_categories, category) if category else ()
            query = api.Query(
                keyword=keyword, category_id=category, category_ids=tuple(leaves),
                attributes={key: tuple(values) for key, values in filters.items() if not key.startswith("__")},
                manufacturers=tuple(filters.get("__manufacturer__", ())),
                packages=tuple(filters.get("__package__", ())),
                packaging=tuple(filters.get("__packaging__", ())),
                in_stock=request["stock"] is True, assembly_stock_only=request["assembly_stock"] is True,
                assembly_tier=tier, page=max(1, int(request["page"])),
                page_size=int(request["size"]), sort_field="price" if request["sort"] else "",
                sort_dir="desc" if request["sort"] == "desc" else "asc",
            )
            page = self.catalog.search(query, cancel)
            groups = []
            note = page.note
            if not api.C_RE.fullmatch(keyword):
                facets = replace(query, attributes={}, manufacturers=(), packages=(), packaging=(), page=1)
                try:
                    groups, *_ = self.catalog.filter_groups(facets, cancel)
                except (api.LCSCError, JLCError) as exc:
                    note = f"{note} Filters unavailable: {exc}".strip()
            page.parts = self.catalog.enrich(page.parts, cancel)
            self.catalog_parts = {part.code: part for part in page.parts}
            return dict(catalog_page=asdict(page), catalog_filters=[asdict(group) for group in groups],
                        message=note or "Catalog search complete.")
        part = self.catalog_parts.get(request["code"])
        if part is None:
            raise ValueError("Select a part from the current results.")
        operation = {"catalog_details": self.catalog.details,
                     "catalog_check_cad": self.catalog.check_cad,
                     "catalog_verify_step": self.catalog.verify_step}[action]
        part = operation(replace(part), cancel)
        self.catalog_parts[part.code] = part
        return dict(catalog_part=asdict(part), message=f"{part.code} details updated.")

    def run_visual(self, action, request):
        from .visualization_ui import matches, VisualizationPanel

        if action == "visual_focus":
            mode = request["mode"]
            if mode == "remove":
                ref = request["reference"]
                remaining = {name: nets for name, nets in self.visual_focus.items() if name != ref}
                hide = set(self.visual_focus.get(ref, ())) - set().union(*remaining.values())
                self.native("visual_ratsnest", mode=mode, hide=sorted(hide))
                self.visual_focus = remaining
            elif mode in ("all", "none", "selection"):
                result = self.native("visual_ratsnest", mode=mode, replace=not self.visual_focused)
                if mode == "selection":
                    self.visual_focus.update(result["components"])
                else:
                    self.visual_focus.clear()
                self.visual_focused = mode != "all"
            else:
                raise ValueError("Invalid ratsnest mode.")
            return dict(focus=self.visual_focus, message="Ratsnest visibility updated.")
        if not self.board_file:
            raise ValueError("Save the PCB before editing visualization settings.")
        path = Path(self.board_file).with_suffix(".traceforge-visual.json")
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        groups = state.get("groups", [])
        individuals = state.get("individuals", {})
        nets = self.visual_nets
        if action == "visual_refresh":
            nets = self.visual_nets = self.native("visual_state")["nets"]
        else:
            if not nets:
                raise ValueError("Refresh nets before editing colors.")
            mode = request["mode"]
            name = request["name"].strip()
            if mode in ("group", "remove_group"):
                old = next((group for group in groups if group["name"] == name), None)
                previous = matches(old["patterns"], nets) if old else set()
                groups = [group for group in groups if group["name"] != name]
                updates = dict.fromkeys(previous)
                if mode == "group":
                    patterns = request["patterns"].strip()
                    members = matches(patterns, nets)
                    if not name or not members:
                        raise ValueError("Provide a group name and patterns that match PCB nets.")
                    taken = set(individuals).union(*(matches(group["patterns"], nets) for group in groups))
                    if members & taken:
                        raise ValueError("Nets already assigned elsewhere: " + ", ".join(sorted(members & taken)[:6]))
                    color = VisualizationPanel.valid_color(request["color"])
                    groups.append(dict(name=name, patterns=patterns, color=color))
                    updates.update(dict.fromkeys(members, color))
            elif mode == "reset":
                updates = dict.fromkeys(nets)
                groups, individuals = [], {}
            elif mode in ("net", "clear_net"):
                if name not in nets or any(name in matches(group["patterns"], nets) for group in groups):
                    raise ValueError("Choose an exact PCB net outside a color group.")
                color = VisualizationPanel.valid_color(request["color"]) if mode == "net" else None
                updates = {name: color}
                if color:
                    individuals[name] = color
                else:
                    individuals.pop(name, None)
            else:
                raise ValueError("Invalid color operation.")
            if updates:
                self.native("visual_colors", updates=updates)
                for name, color in updates.items():
                    nets[name]["color"] = color or ""
            path.write_text(json.dumps(dict(version=1, groups=groups, individuals=individuals), indent=2) + "\n",
                            encoding="utf-8")
        return dict(visual=dict(nets=nets, groups=groups), focus=self.visual_focus,
                    message=f"{len(nets)} PCB nets available.")

    def calculate_bom(self, request):
        from . import bom_cost, bom_identity, bom_source
        from .component_runtime import Worker

        self.bom_proposals = None
        self.bom_replacement = None
        cancel = self.bom_cancel
        if request.get("source") == "live":
            data = self.native("bom_snapshot")
        else:
            worker = Worker()
            worker.cancel = cancel
            cli = shutil.which("kicad-cli") or str(Path(sys.executable).with_name("kicad-cli.exe"))
            data = bom_source.saved_schematic(request["schematic"], worker, cli)

        def progress(index, count, code):
            if not cancel.is_set() and (index == count or index % 8 == 0):
                wx.CallAfter(self.bom_progress, cancel, f"Processed {index}/{count}: {code or 'unassigned'}")

        parts = bom_identity.resolve(data["parts"], cancel, progress)
        result = bom_cost.estimate(parts, int(request["boards"]), float(request["spares"]),
                                   request.get("refresh") is True, cancel, progress)
        result.update(source=data["source"], schematic=data.get("schematic"),
                      source_parts=data["parts"], resolved_parts=parts,
                      identity_resolution={p["reference"]: p.get("identity_source", "saved supplier field")
                                           for p in parts})
        if cancel.is_set():
            raise ValueError("BOM calculation cancelled.")
        self.bom_result = result
        return dict(bom=self.bom_snapshot(),
                    message="BOM cost calculation complete.")

    def bom_snapshot(self):
        from .bom_cost import availability_state

        snapshot = {key: self.bom_result[key] for key in
                ("source", "scope", "unpriced_lines",
                 "known_parts_subtotal_usd", "complete_parts_total_usd")}
        snapshot["lines"] = [dict(line, availability=availability_state(line))
                             for line in self.bom_result["lines"]]
        return snapshot

    def bom_progress(self, cancel, message):
        if not self.closed and self.bom_cancel is cancel and not cancel.is_set():
            self.browser.RunScriptAsync(f"setStatus({json.dumps(message)});")

    def export_bom(self):
        if self.bom_result is None:
            self.send({"error": "Calculate a BOM before exporting."})
            return
        with wx.FileDialog(self, "Export BOM cost", wildcard="JSON report (*.json)|*.json",
                           defaultFile="bom-cost.json",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath()).with_suffix(".json")
        csv_path = path.with_suffix(".csv")
        if csv_path.exists() and wx.MessageBox(
                f"Replace {csv_path.name}?", "Export BOM cost",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
            return
        try:
            path.write_text(json.dumps(self.bom_result, indent=2) + "\n", encoding="utf-8")
            fields = ("lcsc", "mpn", "references", "per_board", "fitted_quantity", "minimum_order",
                      "order_multiple", "requested_spares", "order_quantity", "leftover_quantity",
                      "moq_extra_quantity", "unit_price_usd", "extended_usd", "stock",
                      "observed_at", "status", "assembly_tier", "assembly_stock", "assembly_observed_at")
            with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                observations = self.bom_result.get("assembly_observations", {})
                for row in self.bom_result["lines"]:
                    assembly = observations.get(row["lcsc"], {})
                    writer.writerow(dict(
                        row, references=", ".join(row["references"]),
                        assembly_tier=assembly.get("tier", "Not checked"),
                        assembly_stock=assembly.get("stock"),
                        assembly_observed_at=assembly.get("observed_at", ""),
                    ))
        except OSError as exc:
            self.send({"error": str(exc)})
            return
        self.send({"message": "Exported JSON evidence and CSV cost lines."})

    def run_stitch(self, action, request):
        fence = request.get("fence") is True
        prefix = "tracefence_" if fence else "stitch_"
        if action in ("stitch_load", "stitch_path"):
            self.stitch_review = None
            scene = self.native(prefix + "scene")
            if action == "stitch_path":
                scene["selected_trace"] = self.native("stitch_net_path", net=request["signal_net"])
            self.stitch_scene = (fence, scene)
            return dict(stitch_scene=scene, message="Board and stitching sets loaded.")
        if not self.stitch_scene or self.stitch_scene[0] != fence:
            raise ValueError("Read the board and selection for this via tool first.")
        scene = self.stitch_scene[1]
        if action == "stitch_preview":
            self.stitch_review = None
            from .stitching import settings

            values = dict(request["settings"])
            region_type = request.get("region")
            if fence:
                region = scene["selected_trace"]
                values.update(pattern="trace", pitch_y=values["pitch_x"], offset_x=0, offset_y=0)
            elif region_type == "selected":
                region = scene["selected_region"]
            elif region_type == "polygon":
                region = dict(kind="polygon", points=request["points"])
            else:
                region = dict(kind="board")
            if not region:
                raise ValueError(scene.get("trace_error" if fence else "selection_error")
                                 or "Choose a valid region or trace in KiCad.")
            result = self.native(prefix + "preview", settings=settings(values), region=region,
                                 replace=request.get("replace") or None,
                                 name=request.get("name") or "Ground stitching",
                                 cancel_file=self.cancel.path)
            if result["accepted"]:
                self.stitch_review = (fence, result["token"])
            return dict(stitch_preview=result, message=f"{len(result['accepted'])} accepted sites.")
        if action == "stitch_apply":
            review, self.stitch_review = self.stitch_review, None
            if not review or review[0] != fence:
                raise ValueError("Preview accepted sites before applying.")
            result = self.native(prefix + "apply", token=review[1])
            message = f"Placed {result['count']} vias. Refill zones in KiCad when ready."
        else:
            identity = request["set_id"]
            if not any(row["id"] == identity for row in scene["sets"]):
                raise ValueError("Choose a stitching set from the current board.")
            count = self.native(prefix + action.removeprefix("stitch_"), ids=[identity])
            if action == "stitch_select":
                return dict(message=f"Selected {count} vias.")
            self.stitch_review = None
            message = f"Removed {count} unchanged vias."
        scene = self.native(prefix + "scene")
        self.stitch_scene = (fence, scene)
        return dict(stitch_scene=scene, message=message)

    def run_via_size(self, action, request):
        if action in ("via_size_apply", "via_size_delete"):
            review, self.via_size_review = self.via_size_review, None
            expected = "delete" if action == "via_size_delete" else "resize"
            if not review or review[0] != expected:
                raise ValueError("Review the proposed via changes first.")
            operation = "via_manage_delete" if expected == "delete" else "via_manage_apply"
            result = self.native(operation, token=review[1])
            try:
                inventory = self.native("via_manage_inventory")
            except (OSError, ValueError, RuntimeError) as exc:
                return dict(via_inventory_stale=True, message=f"{result['message']} "
                            f"Refresh the via inventory manually: {exc}")
            return dict(via_inventory=inventory, message=result["message"])
        if action == "via_size_inventory":
            self.via_size_review = None
            result = self.native("via_manage_inventory")
            return dict(via_inventory=result, message=f"{result['total']} placed vias.")
        filters = {"selected_only": request.get("selected_only") is True}
        if request.get("net"):
            filters["net"] = str(request["net"])
        if request.get("size"):
            filters["diameter_mm"], filters["drill_mm"] = map(float, request["size"].split("/"))
        if action == "via_size_select":
            result = self.native("via_manage_select", **filters)
            return dict(message=f"Selected {result['count']} matching vias.")
        self.via_size_review = None
        if action == "via_size_review_delete":
            result = self.native("via_manage_prepare_delete", **filters)
            count = sum(row["status"] == "candidate" for row in result["vias"])
            if count:
                self.via_size_review = ("delete", result["token"])
            return dict(via_review=result, delete_count=count,
                        message=f"{count} unlocked vias match the deletion filter.")
        from .via_manager import analyze

        prepared = self.native("via_manage_prepare", **filters,
                               target_diameter_mm=float(request["diameter"]),
                               target_drill_mm=float(request["drill"]),
                               cancel_file=self.cancel.path)
        result = analyze(prepared, cancel=self.cancel)
        if result["ready"]:
            self.via_size_review = ("resize", result["token"])
        return dict(via_review=result, resize_ready=len(result["ready"]),
                    message=f"{len(result['ready'])} vias cleared for resizing.")

    def run_text_layout(self, action, request):
        token, self.text_token = self.text_token, None
        if action == "text_layout_preview":
            result = self.native(action, **request["settings"])
            if result["counts"]["move"]:
                self.text_token = result["token"]
            return dict(text_layout=result, message=result["message"])
        if not token:
            raise ValueError("Preview movable labels first.")
        result = self.native(action, token=token)
        return dict(message=result["message"])

    def run_fillet(self, action, request):
        token, self.fillet_token = self.fillet_token, None
        if action == "fillet_preview":
            result = self.native(action, radius=float(request["radius"]),
                                 scope=request["scope"], net=request["net"],
                                 adaptive=request.get("adaptive") is True)
            if result["accepted"]:
                self.fillet_token = result["token"]
            return dict(fillet=result, message=f"{result['accepted']} eligible corners.")
        if action == "fillet_apply":
            if not token:
                raise ValueError("Preview eligible corners first.")
            result = self.native(action, token=token)
            return dict(message=f"Rounded {result['added']} corners.")
        result = self.native(action, scope=request["scope"])
        return dict(message=f"Restored {result['restored']} corners.")

    def run_signals(self, action, request):
        if self.tools is None:
            raise ValueError("Signal-path analysis needs a live PCB session.")
        if action == "signals_chain_selection":
            refs = list(dict.fromkeys(item["ref"] for item in self.native("selection") if item.get("ref")))
            if not refs:
                raise ValueError("Select footprints in PCB Editor first.")
            return dict(chain_selection=dict(field=request["field"], references=refs),
                        message=f"Read {len(refs)} selected footprints.")
        if action.startswith("signals_endpoint_"):
            return self.run_signal_endpoints(action, request)
        if action.startswith("signals_chains_"):
            return self.edit_signal_chains(action, request)
        if action == "signals_refresh":
            self.signal_results = None
            groups = self.tools.evaluate()
            rows = [
                dict(group=group.group.name, name=row.chain.name, status=row.status,
                     length=row.length_mm, delay=row.total_ps if row.timing_complete else None,
                     target=row.target_ps, skew=row.pair_skew_ps, spread=group.spread_ps)
                for group in groups for row in group.chains
            ]
            routing = self.tools.routing_configuration()
            self.signal_results = groups
            return dict(signals=rows, routing=routing,
                        message=f"{len(rows)} signal paths. {self.tools.source()}")
        if action == "signals_focus":
            group_name, name = request["group"], request.get("name")
            group = next((item for item in self.signal_results or ()
                          if item.group.name == group_name), None)
            if group is None or (name and not any(row.chain.name == name for row in group.chains)):
                raise ValueError("Refresh signal paths before highlighting.")
            count = (self.tools.highlight_chain(group_name, name) if name
                     else self.tools.highlight_group(group_name))
            return dict(message=f"Highlighted {count} items.")
        if action == "signals_focus_groups":
            names = request.get("groups")
            known = {result.group.name for result in self.signal_results or ()}
            if (not isinstance(names, list) or not names
                    or any(not isinstance(name, str) or name not in known for name in names)):
                raise ValueError("Select groups from a current signal-path scan.")
            groups = list(dict.fromkeys(names))
            count = (self.tools.highlight_group(groups[0]) if len(groups) == 1
                     else self.tools.highlight_groups(groups))
            return dict(message=f"Highlighted {count} items across {len(groups)} groups.")
        if action == "signals_clear":
            self.tools.clear()
            return dict(message="Highlight cleared.")
        if action in ("signals_highlight_chain", "signals_highlight_group"):
            return dict(message=self.tools.highlight_selection(action == "signals_highlight_group"))
        if action == "signals_zoom":
            return dict(message=self.tools.zoom_selection())
        if action == "signals_targets":
            if not self.signal_results:
                raise ValueError("Refresh signal paths before writing targets.")
            return dict(message=self.tools.write_targets(self.signal_results))
        return dict(message=self.tools.export_paths())

    def run_signal_endpoints(self, action, request):
        if self.endpoints is None:
            raise ValueError("Endpoint detection requires a live PCB session.")
        if action == "signals_endpoint_add":
            if not self.endpoint_review or "primary" not in self.endpoint_review:
                raise ValueError("Detect and review a routed path first.")
            message = self.endpoints.add(self.endpoint_review, request["group"], request["name"])
            self.endpoint_review = self.signal_results = None
            reply = self.edit_signal_chains("signals_chains_load", {})
            return dict(reply, message=message, endpoint_added=True)
        previous, self.endpoint_review = self.endpoint_review, None
        options = dict(max_ohms=float(request["ohms"]), capacitors=request["caps"] is True,
                       include_pair=request["pair"] is True, all_resistors=request["resistors"] is True)
        if action == "signals_endpoint_pick":
            first = self.endpoints.pick("TraceForge: click FIRST path endpoint. Esc cancels.")
            second = self.endpoints.pick("TraceForge: click SECOND path endpoint. Esc cancels.")
            options["endpoints"] = [first["id"], second["id"]]
        elif action == "signals_endpoint_choose":
            choices = (previous or {}).get("choices", [])
            index = int(request["index"])
            if not 0 <= index < len(choices):
                raise ValueError("Detect endpoint choices again.")
            options["endpoints"] = choices[index]["endpoints"]
        result = self.endpoints.detect(**options)
        self.endpoint_review = result
        return dict(endpoint_review=result, message="Review the routed path before adding it.")

    def edit_signal_chains(self, action, request):
        from .chains import Config, config_from_data, config_to_json

        if not self.tools.chain_config or not self.tools.commit_chains:
            raise ValueError("The live chain editor is unavailable.")
        if action == "signals_chains_load":
            data = json.loads(config_to_json(self.tools.chain_config() or Config([])))
            return dict(chain_config=data, message="Current xSignal definitions loaded.")
        if action == "signals_chains_find":
            def refs(key):
                return [item.strip() for item in request[key].replace(";", ",").split(",") if item.strip()]

            sources, destinations = refs("sources"), refs("destinations")
            if not sources or not destinations:
                raise ValueError("Enter source and destination reference designators.")
            found = self.tools.find_chains(sources, destinations, float(request["ohms"]), request["caps"] is True)
            return dict(chain_candidates=[asdict(chain) for chain in found],
                        message=f"Found {len(found)} candidate paths.")
        config = config_from_data(request["config"])
        for value in [config.pad_to_die_ps_per_mm] + [
            value for group in config.groups for value in (group.skew_ps, group.pair_skew_ps, group.stub_max_ps)
            if value is not None
        ]:
            if not math.isfinite(value) or value < 0:
                raise ValueError("Timing limits must be finite and nonnegative.")
        for group in config.groups:
            members = {chain.name: chain for chain in group.chains}
            if not group.name.strip() or not members:
                raise ValueError("Each group must have a name and at least one path.")
            for chain in group.chains:
                if not chain.name.strip() or not chain.nets or any(not net.strip() for net in chain.nets):
                    raise ValueError("Every path needs a name and one or more nets.")
                if chain.pair and (chain.pair == chain.name or chain.pair not in members
                                   or members[chain.pair].pair != chain.name):
                    raise ValueError(f"{group.name}/{chain.name}: assign both members of the differential pair.")
        path = self.tools.commit_chains(config)
        self.signal_results = None
        return dict(chain_saved=True,
                    message=f"Saved {len(config.groups)} groups to {path.name}. Refresh to evaluate timing.")

    def run_fanout(self, action, request):
        if action == "fanout_analyze":
            self.fanout_preview = None
            self.fanout = self.native(action)
            return dict(fanout=self.fanout, message="Footprint analyzed.")
        if not self.fanout:
            raise ValueError("Analyze a selected BGA first.")
        footprint = self.fanout["id"]
        if action in ("fanout_preview", "fanout_suggest"):
            self.fanout_preview = None
            options = dict(footprint=footprint, settings=validate_fanout(request["settings"]))
            if action == "fanout_suggest":
                return dict(suggestions=self.native(action, **options), message="Settings reviewed.")
            result = self.native(action, **options, cancel_file=self.cancel.path)
            self.fanout_preview = result
            return dict(fanout_preview=result, message=f"{len(result['accepted'])} accepted routes.")
        if action == "fanout_apply":
            preview, self.fanout_preview = self.fanout_preview, None
            if not preview or not preview["accepted"]:
                raise ValueError("Preview accepted routes before applying.")
            result = self.native(action, token=preview["token"])
            message = f"Placed fanout for {result['pads']} pads."
        else:
            self.fanout_preview = None
            result = self.native(action, footprint=footprint,
                                 expected_count=self.fanout["managed_items"])
            message = f"Removed {result['removed']} unchanged fanout items."
        self.fanout = self.native("fanout_analyze", footprint=footprint)
        return dict(fanout=self.fanout, message=message + " Refill zones in KiCad when ready.")

    def clone_template(self, action):
        save = action == "clone_template_save"
        if save and self.source is None:
            raise ValueError("Record a source layout before saving a template.")
        with wx.FileDialog(self, "Save layout template" if save else "Load layout template",
                           wildcard="JSON (*.json)|*.json",
                           style=(wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) if save else
                           (wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        if save:
            path.write_text(json.dumps(self.source, indent=2, ensure_ascii=False), encoding="utf-8")
            self.send(dict(message=f"Saved layout template to {path.name}."))
        else:
            source = json.loads(path.read_text(encoding="utf-8"))
            _validate_snapshot(source)
            self.source = source
            self.send(self.clone_source_reply(f"Loaded {path.name}.", "both", True))

    def clone_source_reply(self, message, mode, graphics):
        return dict(message=message, counts=self.source.get("assets", {}).get("counts", {}),
                    anchors=[item["ref"] for item in self.source["items"]],
                    scene=make_scene(self.source, mode=mode, graphics=graphics))

    def run_clone(self, action, request):
        mode = request.get("mode", "both")
        if mode not in assets.MODES:
            raise ValueError("Invalid clone mode.")
        graphics = request.get("graphics") is True
        scope = request.get("scope", "selection")
        if scope not in ("selection", "hierarchy"):
            raise ValueError("Invalid source scope.")
        selection = dict(scope=scope, parent_levels=int(request.get("parent_levels", 0)))
        if action == "record":
            self.source = self.native("layout_clone_capture", **selection,
                                      mode=mode, include_graphics=graphics)
            return self.clone_source_reply(f"Recorded {len(self.source['items'])} footprints.", mode, graphics)
        if self.source is None:
            raise ValueError("Record the source layout first.")
        options = dict(template=self.source, mode=mode, include_graphics=graphics,
                       group_cloned=request.get("group_cloned") is True,
                       check_clearance=request.get("clearance") is not False,
                       selective=request.get("selective") is True,
                       accept_value_changes=request.get("values") is True,
                       allow_partial=request.get("partial") is True,
                       anchor=request.get("anchor") or None)
        if action == "grid":
            result = self.native("layout_clone_grid", **options,
                                 columns=int(request["columns"]),
                                 grid_x=float(request["grid_x"]), grid_y=float(request["grid_y"]))
            return self.applied(result)
        selection = {key: self.source[key] for key in selection if key in self.source}
        target = self.native("layout_clone_target", **selection)["snapshot"]
        options["overrides"] = request.get("overrides") or {}
        plan = make_plan(self.source, target, anchor_source=options["anchor"],
                         overrides=options["overrides"],
                         accept_value_changes=options["accept_value_changes"],
                         allow_partial=options["allow_partial"])
        plan = assets.plan_options(self.source, target, plan,
                                   mode, graphics,
                                   selective=options["selective"])
        if action == "apply" and plan["can_apply"]:
            return self.applied(self.native("layout_clone_apply", **options,
                                            expected_target=target))
        return dict(message="Ready to apply." if plan["can_apply"] else "Apply blocked.",
                    issues=plan["issues"], warnings=plan["warnings"], pairs=plan["pairs"],
                    match_choices={item["ref"]: [candidate["ref"] for candidate in target["items"]
                                                 if matching_geometry(item, candidate)]
                                   for item in self.source["items"]},
                    scene=make_scene(self.source, target, plan,
                                     mode, graphics))

    @staticmethod
    def applied(result):
        return dict(message=f"Applied {result['moved']} footprints and "
                            f"{result['cloned_assets']} assets. "
                            + (f"Created {result['groups_created']} groups. " if result.get("groups_created") else "")
                            + result.get("grouping_note", "") + " "
                            + result.get("selection_note", "") + " Refill zones with B when ready.",
                    warnings=[f"Skipped {count} items on {net}"
                              for net, count in sorted(result.get("skipped_nets", {}).items())])
