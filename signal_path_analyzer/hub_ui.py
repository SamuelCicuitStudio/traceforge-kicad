"""TraceForge panel: one floating window over the KiCad PCB editor with every TraceForge tool.

The native launcher uses KiCad's bundled Python and wxPython. On Windows the panel stays
above KiCad while either application has focus, without owning the editor window.
Shortcuts are registered by the panel itself and work while KiCad (or the panel) has focus.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import wx
import wx.lib.agw.hypertreelist as htl

from . import __version__
from .api_access import ApiAccess
from .chains import GroupResult
from .signal_presentation import describe_signal

SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / "TraceForge" / "settings.json"
DEFAULT_SHORTCUTS = {
    "highlight_chain": "Ctrl+Alt+H",
    "highlight_group": "Ctrl+Alt+G",
    "clear": "Ctrl+Alt+C",
    "write_targets": "Ctrl+Alt+W",
    "export_paths": "Ctrl+Alt+E",
    "toggle_panel": "Ctrl+Alt+T",
}
LABELS = {
    "highlight_chain": "Highlight chain of KiCad selection",
    "highlight_group": "Highlight group of KiCad selection",
    "clear": "Clear selection",
    "write_targets": "Write DRC targets",
    "export_paths": "Export signal paths (CSV)",
    "toggle_panel": "Show / hide this panel",
}
# Status text and symbols remain visible alongside semantic row colours.
MARK = {"ok": "✔", "short": "▲", "long": "▼", "pending": "…", "routed": "•",
        "unprofiled": "✖"}


@dataclass
class Tools:
    """Callbacks bound to the live board by the action entry point."""

    evaluate: Callable[[], list[GroupResult]]
    highlight_chain: Callable[[str, str], int]
    highlight_group: Callable[[str], int]
    highlight_selection: Callable[[bool], str]  # True = whole group
    clear: Callable[[], None]
    write_targets: Callable[[list[GroupResult]], str]
    export_paths: Callable[[], str]
    save_config: Callable[[], str] = lambda: "nothing to save"
    source: Callable[[], str] = lambda: ""  # e.g. "xsignals.json" or "auto-detected"
    edit_chains: Callable[[wx.Window], str] = lambda parent: "chain editor unavailable"
    zoom_selection: Callable[[], str] = lambda: "zoom unavailable"
    highlight_groups: Optional[Callable[[list[str]], int]] = None
    routing_configuration: Callable[[], dict] = lambda: {}


class BusyOverlay(wx.Panel):
    """Rotating loader centered over the active tab's main results area."""

    def __init__(self, parent, dark):
        super().__init__(parent, size=(250, 132))
        self.dark = dark
        self.phase = 0
        self.message = "Scanning board..."
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)

    def set_message(self, message):
        self.message = message
        self.Refresh(False)

    def advance(self):
        self.phase = (self.phase + 1) % 12
        self.Refresh(False)

    def on_paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        size = self.GetClientSize()
        background = wx.Colour("#253449" if self.dark else "#F4F8FC")
        border = wx.Colour("#59748E" if self.dark else "#A8BED1")
        primary = wx.Colour("#7DCFFF" if self.dark else "#145FA0")
        dim = wx.Colour("#39536E" if self.dark else "#B2CBDD")
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        dc.SetPen(wx.Pen(border, 1))
        dc.SetBrush(wx.Brush(background))
        dc.DrawRoundedRectangle(1, 1, size.width - 2, size.height - 2, 10)
        dc.SetPen(wx.TRANSPARENT_PEN)
        for index in range(12):
            strength = (12 - (index - self.phase) % 12) / 12
            color = wx.Colour(
                *(
                    round(a + strength * (b - a))
                    for a, b in zip(
                        (dim.Red(), dim.Green(), dim.Blue()),
                        (primary.Red(), primary.Green(), primary.Blue()),
                    )
                )
            )
            dc.SetBrush(wx.Brush(color))
            angle = 2 * math.pi * index / 12 - math.pi / 2
            dc.DrawCircle(
                round(size.width / 2 + 24 * math.cos(angle)), round(52 + 24 * math.sin(angle)), 4
            )
        dc.SetTextForeground(primary)
        dc.SetFont(self.GetFont().Bold())
        text_width, _ = dc.GetTextExtent(self.message)
        dc.DrawText(self.message, max(8, (size.width - text_width) // 2), 99)


def load_shortcuts() -> dict[str, str]:
    try:
        saved = json.loads(SETTINGS.read_text(encoding="utf-8")).get("shortcuts", {})
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULT_SHORTCUTS, **{k: v for k, v in saved.items() if k in DEFAULT_SHORTCUTS}}


def save_shortcuts(shortcuts: dict[str, str]) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS.exists():
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data["shortcuts"] = shortcuts
    SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def parse_shortcut(text: str) -> Optional[tuple[int, int]]:
    """'Ctrl+Alt+H' -> (wx.MOD_* flags, key code); None when invalid or without a modifier."""

    parts = [p.strip() for p in text.split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods = {"ctrl": wx.MOD_CONTROL, "alt": wx.MOD_ALT, "shift": wx.MOD_SHIFT, "win": wx.MOD_WIN}
    flags = 0
    for p in parts[:-1]:
        if p.lower() not in mods:
            return None
        flags |= mods[p.lower()]
    key = parts[-1].upper()
    if len(key) == 1 and key.isalnum():
        return flags, ord(key)
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        return flags, wx.WXK_F1 + int(key[1:]) - 1
    return None


def kicad_dark_theme() -> bool:
    """KiCad 10 appearance.app_theme: 0 = follow system, 1 = light, 2 = dark."""

    path = Path(os.environ.get("APPDATA", Path.home())) / "kicad" / "10.0" / "kicad_common.json"
    try:
        theme = json.loads(path.read_text(encoding="utf-8"))["appearance"]["app_theme"]
    except (OSError, ValueError, KeyError):
        theme = 0
    if theme == 2:
        return True
    if theme == 1:
        return False
    return wx.SystemSettings.GetAppearance().IsDark()


def _kicad_pid(expected: Optional[int] = None) -> Optional[int]:
    """Process id of a visible KiCad PCB Editor window (Windows only)."""

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.endswith("PCB Editor"):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if expected is None or pid.value == expected:
                    found.append(pid.value)
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def _foreground_pid() -> Optional[int]:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


class ShortcutDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, shortcuts: dict[str, str]):
        super().__init__(parent, title="TraceForge shortcuts")
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=10)
        self.fields: dict[str, wx.TextCtrl] = {}
        for key, label in LABELS.items():
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            field = wx.TextCtrl(self, value=shortcuts[key], size=(140, -1))
            self.fields[key] = field
            grid.Add(field)
        note = wx.StaticText(self, label="Format: Ctrl+Alt+H, Ctrl+Shift+F5. Needs a modifier.")
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(grid, 0, wx.ALL, 12)
        box.Add(note, 0, wx.LEFT | wx.RIGHT, 12)
        box.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(box)

    def values(self) -> dict[str, str]:
        return {k: f.GetValue().strip() for k, f in self.fields.items()}


class TraceForgePanel(wx.Frame):
    """Floating TraceForge window: timing snapshots refreshed on demand."""

    def __init__(self, tools: Tools, stitching=None, endpoints=None, native_info=None):
        style = wx.DEFAULT_FRAME_STYLE | wx.FRAME_TOOL_WINDOW
        super().__init__(None, title=f"TraceForge {__version__}", size=(1160, 760), style=style)
        self.tools, self.results = tools, []
        self.endpoints = endpoints
        from .refresh_policy import RefreshPolicy

        self.refresh_policy = RefreshPolicy()
        self.native_call = stitching
        self.change_check_pending = False
        self.auto_refresh_later = None
        self.auto_check_deferred = False
        self.busy, self.open_groups = False, set()
        self.api = ApiAccess()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="traceforge-api")
        self.actions_pending = 0
        self.closing = False
        self.hotkey_ids: dict[int, str] = {}
        self.SetMinSize((520, 260))
        # Overlay: on top only while KiCad (or this panel) is the active application. A
        # cross-process window owner is avoided on purpose; Windows can hang or misbehave with it.
        editor_pid = os.environ.get("TRACEFORGE_EDITOR_PID", "")
        self.editor_pid = int(editor_pid) if editor_pid.isdecimal() else None
        self.kicad_pid = self.editor_pid or _kicad_pid()
        self.missing_editor_checks = 0
        self.on_top = False
        self.overlay = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_overlay, self.overlay)
        self.overlay.Start(400)

        self.dark = kicad_dark_theme()
        self.colors = (
            {
                "ok": "#6EE7A0",
                "warning": "#FFD166",
                "error": "#FF8585",
                "pending": "#A8B4C7",
                "routed": "#7DCFFF",
            }
            if self.dark
            else {
                "ok": "#136C3B",
                "warning": "#895100",
                "error": "#B42332",
                "pending": "#586477",
                "routed": "#145FA0",
            }
        )
        icon = (
            Path(__file__).resolve().parents[1]
            / "icons"
            / ("traceforge-dark-48.png" if self.dark else "traceforge-light-48.png")
        )
        self.SetIcon(wx.Icon(str(icon), wx.BITMAP_TYPE_PNG))
        self.notebook = wx.Notebook(self)
        root = wx.Panel(self.notebook)
        if self.dark:
            root.SetBackgroundColour("#222C3A")
            root.SetForegroundColour("#E5EDF8")
        bar = wx.BoxSizer(wx.HORIZONTAL)
        buttons = (
            ("Highlight chain", self.on_chain),
            ("Highlight groups", self.on_group),
            ("Zoom selection", self.on_zoom),
            ("Clear", self.on_clear),
            ("Write DRC targets", self.on_write),
            ("Export paths", self.on_export),
            ("Chain editor…", self.on_edit),
            ("Shortcuts…", self.on_shortcuts),
        )
        for label, handler in buttons:
            btn = wx.Button(root, label=label, style=wx.BU_EXACTFIT)
            btn.Bind(wx.EVT_BUTTON, handler)
            bar.Add(btn, 0, wx.RIGHT, 4)
        self.refresh = wx.Button(root, label="Refresh (F5)", style=wx.BU_EXACTFIT)
        self.refresh.SetToolTip(
            "Force refresh. Tabs also refresh when opened or revisited "
            "after a board change. No continuous polling."
        )
        self.refresh.Bind(wx.EVT_BUTTON, self.on_refresh)
        bar.AddStretchSpacer()
        self.active_operation = None
        self.cancel_operation = wx.Button(self, label="Cancel operation", style=wx.BU_EXACTFIT)
        self.cancel_operation.SetToolTip("Stop a read-only scan or preview. "
                                         "Board edits are atomic.")
        self.cancel_operation.Disable()
        self.cancel_operation.Bind(wx.EVT_BUTTON, self.on_cancel_operation)
        bar.Add(self.refresh)
        refresh_id = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self.on_refresh, id=refresh_id)
        self.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_NORMAL, wx.WXK_F5, refresh_id)]))

        self.tree = htl.HyperTreeList(
            root,
            agwStyle=(
                wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_FULL_ROW_HIGHLIGHT
                | wx.TR_LINES_AT_ROOT | wx.TR_MULTIPLE
            ),
        )
        if self.dark:
            self.tree.SetBackgroundColour("#19212D")
            self.tree.SetForegroundColour("#E5EDF8")
        right = wx.ALIGN_RIGHT
        columns = (
            ("Group / signal type / chain", 310, wx.ALIGN_LEFT),
            ("Total ps", 80, right),
            ("Target ps", 80, right),
            ("Δ ps", 70, right),
            ("P−N ps", 70, right),
            ("Source PCB ps", 95, right),
            ("Status", 160, wx.ALIGN_LEFT),
            ("Chain track mm", 110, right),
            ("Tunable mm", 100, right),
            ("Source PCB mm", 100, right),
        )
        for title, width, align in columns:
            self.tree.AddColumn(title, width=width, flag=align)
        self.tree.AddRoot("signals")
        self.rows = {}
        self.row_states = {}
        self.topology = None
        self.tree.GetMainWindow().Bind(wx.EVT_LEFT_UP, self.on_row_click)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_signal_selection)
        self.status = wx.StaticText(root, label="Click Refresh to load timing from KiCad.")
        self.snapshot = wx.StaticText(root, label="No timing snapshot yet. Manual refresh only.")
        self.snapshot.SetForegroundColour(self.colors["pending"])
        self.tree.GetMainWindow().SetToolTip(
            "Ctrl+click to select several groups; Shift+click selects a range. "
            "Click Highlight groups to highlight them together. "
            "Chain track mm = all tracks and arcs across every net in the chain. "
            "Tunable mm = last net; Source PCB = first net before "
            "series parts, not a dangling branch. "
            "Lengths exclude via barrels, pad-to-die lengths, and component internals. "
            "All net branches are summed; KiCad tunes a point-to-point path. "
            "Timing includes the configured via and pad-to-die delay estimates."
        )
        self.status.SetForegroundColour(self.colors["pending"])

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
        self.stackup_display = wx.StaticText(
            root, label="Stackup: refresh to load board construction")
        box.Add(self.stackup_display, 0, wx.EXPAND | wx.ALL, 6)
        self.routing_geometry = wx.ListCtrl(root, style=wx.LC_REPORT, size=(-1, 145))
        for index, (title, width) in enumerate([
                ("Computed profile", 185), ("Netclasses", 140), ("Type", 80),
                ("Target ohms", 90), ("Signal layer", 90), ("Reference plane", 120),
                ("Width mm", 100), ("Pair gap mm", 100), ("Source / status", 220)]):
            self.routing_geometry.InsertColumn(index, title, width=width)
        box.Add(self.routing_geometry, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.geometry_note = wx.StaticText(root, label="")
        box.Add(self.geometry_note, 0, wx.EXPAND | wx.ALL, 6)

        detect = wx.Button(root, label="Detect path between 2 selected PCB items...")
        detect.Enable(endpoints is not None)
        detect.Bind(wx.EVT_BUTTON, self.on_endpoints)
        box.Add(detect, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        legend = wx.BoxSizer(wx.HORIZONTAL)
        self.summary = {}
        for key, label in (
            ("ok", "OK"),
            ("warning", "Warning"),
            ("error", "Error"),
            ("pending", "Pending"),
            ("routed", "Routed"),
        ):
            chip = wx.StaticText(root, label=f"\u25cf {label}: 0")
            chip.SetForegroundColour(self.colors[key])
            chip.SetFont(chip.GetFont().Bold())
            self.summary[key] = chip
            legend.Add(chip, 0, wx.RIGHT, 18)
        box.Add(legend, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.tuning_hint = wx.StaticText(
            root,
            label=(
                "[DIFF] = differential pair: KiCad 8 for pair length, 9 "
                "for P/N skew. [SE] = single-ended: KiCad 7."
            ),
        )
        box.Add(self.tuning_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        box.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        box.Add(self.snapshot, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        box.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        root.SetSizer(box)

        from .via_tools_ui import ViaToolsPanel
        from .workspace_ui import ToolWorkspace, utility_window
        from .workspaces import tool_id

        self.signals_workspace = ToolWorkspace(self.notebook, self, ['Paths / timing', 'Unrouted'])
        self.signals_workspace.add(root, 'Paths / timing')
        from .unrouted_ui import UnroutedPanel

        self.unrouted = UnroutedPanel(self.signals_workspace.book, self, stitching)
        self.signals_workspace.add(self.unrouted, 'Unrouted')
        self.notebook.AddPage(self.signals_workspace, 'Signals')
        self.layout_workspace = ToolWorkspace(self.notebook, self,
                                              ['Layout Clone', 'Rotation', 'References'])
        from .board_rotate_ui import BoardRotatePanel
        from .traceforge_auto_text import create_tab as create_auto_text_tab
        from .traceforge_layout_clone import create_tab

        self.layout_clone = create_tab(self.layout_workspace.book, stitching)
        self.rotation = BoardRotatePanel(self.layout_workspace.book, self, stitching)
        self.auto_text = create_auto_text_tab(self.layout_workspace.book, self, stitching)
        for page, label in [(self.layout_clone, 'Layout Clone'), (self.rotation, 'Rotation'),
                            (self.auto_text, 'References')]:
            self.layout_workspace.add(page, label)
        self.notebook.AddPage(self.layout_workspace, 'Layout')
        self.via_tools = ViaToolsPanel(self.notebook, self, stitching)
        self.stitching = self.via_tools.stitching
        self.trace_fence = self.via_tools.fencing
        self.via_array = self.via_tools.array
        self.notebook.AddPage(self.via_tools, 'Vias')
        from .trace_tools_ui import TraceToolsPanel

        self.trace_tools = TraceToolsPanel(self.notebook, self, stitching)
        self.trace_cleanup = self.trace_tools.cleanup
        self.fanout = self.trace_tools.fanout
        self.notebook.AddPage(self.trace_tools, 'Routing')
        from .components_ui import ComponentsPanel

        board_file = (native_info or {}).get('board')
        self.components = ComponentsPanel(self.notebook, self, stitching, board_file)
        self.notebook.AddPage(self.components, 'Components')
        from .bom_cost_ui import BomCostPanel
        from .manufacturing_ui import ManufacturingPanel

        self.manufacturing_workspace = ToolWorkspace(self.notebook, self,
                                                     ['Manufacturing', 'BOM Cost'])
        self.manufacturing = ManufacturingPanel(self.manufacturing_workspace.book, self, board_file)
        self.bom_cost = BomCostPanel(self.manufacturing_workspace.book, self, stitching, board_file)
        self.manufacturing_workspace.add(self.manufacturing, 'Manufacturing')
        self.manufacturing_workspace.add(self.bom_cost, 'BOM Cost')
        self.notebook.AddPage(self.manufacturing_workspace, 'Manufacturing')
        from .about_ui import AboutPanel
        from .visualization_ui import VisualizationPanel

        self.view_window = utility_window(self, 'TraceForge - View')
        self.visualization = VisualizationPanel(self.view_window, self, stitching, board_file)
        view_box = wx.BoxSizer(wx.VERTICAL)
        view_box.Add(self.visualization, 1, wx.EXPAND)
        self.view_window.SetSizer(view_box)
        self.about_window = utility_window(self, 'About TraceForge')
        self.about = AboutPanel(self.about_window, self.dark, native_info)
        about_box = wx.BoxSizer(wx.VERTICAL)
        about_box.Add(self.about, 1, wx.EXPAND)
        self.about_window.SetSizer(about_box)
        self._utility = None
        self._normalizing_tool = tool_id
        if self.dark:
            self.stitching.SetBackgroundColour("#222C3A")
            self.stitching.SetForegroundColour("#E5EDF8")
        frame_box = wx.BoxSizer(wx.VERTICAL)
        cancel_bar = wx.BoxSizer(wx.HORIZONTAL)
        for title, target in [('View', 'view'), ('About / Settings', 'about')]:
            utility = wx.Button(self, label=title)
            utility.Bind(wx.EVT_BUTTON, lambda event, target=target: self.activate_tool(target))
            cancel_bar.Add(utility, 0, wx.ALL, 4)
        cancel_bar.AddStretchSpacer()
        cancel_bar.Add(self.cancel_operation, 0, wx.ALL, 4)
        frame_box.Add(cancel_bar, 0, wx.EXPAND)
        frame_box.Add(self.notebook, 1, wx.EXPAND)
        self.activity = BusyOverlay(self, self.dark)
        self.activity.Hide()
        self.activity_count = 0
        self.activity_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_activity_tick, self.activity_timer)
        self.SetSizer(frame_box)
        self.SetMinSize((820, 560))
        self.SetSize((1160, 720))

        self.Bind(wx.EVT_HOTKEY, self.on_hotkey)
        self.Bind(wx.EVT_SIZE, self.on_resize)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.register_shortcuts(load_shortcuts())
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_open)
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        try:
            preferences = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
            for name, workspace in [('signals', self.signals_workspace),
                                    ('layout', self.layout_workspace), ('vias', self.via_tools),
                                    ('routing', self.trace_tools),
                                    ('components', self.components),
                                    ('manufacturing', self.manufacturing_workspace)]:
                index = preferences.get('workspace_tools', {}).get(name, 0)
                if isinstance(index, int) and 0 <= index < workspace.selector.GetCount():
                    workspace.selector.SetSelection(index)
                    workspace.book.SetSelection(index)
            self.activate_tool(preferences.get('workspace', 'signals.paths'))
        except (OSError, ValueError):
            logging.exception('Cannot restore workspace preferences')
        wx.CallAfter(self.schedule_auto_refresh)

    def current_tool(self):
        index = self.notebook.GetSelection()
        if index == 0:
            return ('signals.paths', 'signals.unrouted')[self.signals_workspace.active_index]
        if index == 1:
            return ('layout.clone', 'layout.rotate', 'layout.references')[
                self.layout_workspace.active_index]
        if index == 2:
            return ('vias.stitching', 'vias.fencing', 'vias.array', 'vias.sizes',
                    'vias.inspector')[self.via_tools.active_index]
        if index == 3:
            return ('routing.cleanup', 'routing.teardrops', 'routing.corners',
                    'routing.fanout')[self.trace_tools.active_index]
        if index == 4:
            return ('components.search', 'components.assets', 'components.library')[
                self.components.selector.GetSelection()]
        return ('manufacturing', 'manufacturing.cost')[self.manufacturing_workspace.active_index]

    def legacy_tab(self):
        from .workspaces import legacy_index

        return legacy_index(self.current_tool())

    def workspace_changed(self):
        if not hasattr(self, 'activity'):
            return
        self.remember_workspace()
        self.position_activity()
        if self.current_tool() == 'signals.unrouted':
            wx.CallAfter(self.unrouted.on_refresh)
        self.schedule_auto_refresh()

    def remember_workspace(self):
        try:
            data = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
            data['workspace'] = self.current_tool()
            data['workspace_tools'] = {
                'signals': self.signals_workspace.active_index,
                'layout': self.layout_workspace.active_index,
                'vias': self.via_tools.active_index,
                'routing': self.trace_tools.active_index,
                'components': self.components.selector.GetSelection(),
                'manufacturing': self.manufacturing_workspace.active_index}
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(data, indent=2) + '\n')
        except (OSError, ValueError):
            logging.exception('Cannot save workspace preferences')

    def activate_tool(self, target):
        from .workspaces import tool_id

        target = tool_id(target)
        if target in ('view', 'about'):
            window = self.view_window if target == 'view' else self.about_window
            window.Show()
            window.Raise()
            if target == 'view' and not self.visualization.nets:
                self.visualization.on_refresh()
            return
        group, index = ({
            'signals.paths': (0, 0), 'signals.unrouted': (0, 1),
            'layout.clone': (1, 0), 'layout.rotate': (1, 1), 'layout.references': (1, 2),
            'vias.stitching': (2, 0), 'vias.fencing': (2, 1), 'vias.array': (2, 2),
            'vias.sizes': (2, 3), 'vias.inspector': (2, 4),
            'routing.cleanup': (3, 0), 'routing.teardrops': (3, 1),
            'routing.corners': (3, 2), 'routing.fanout': (3, 3),
            'components.search': (4, 0), 'components.assets': (4, 1),
            'components.library': (4, 2), 'manufacturing': (5, 0),
            'manufacturing.cost': (5, 1)})[target]
        if group in (0, 1):
            (self.signals_workspace if group == 0 else self.layout_workspace).select(index)
        elif group in (2, 3):
            page = self.via_tools if group == 2 else self.trace_tools
            page.selector.SetSelection(index)
            page.book.SetSelection(index)
        elif group == 4:
            self.components.selector.SetSelection(index)
            self.components.book.SetSelection(index)
        elif group == 5:
            self.manufacturing_workspace.select(index)
        self.notebook.SetSelection(group)
        self.workspace_changed()

    def on_tab_open(self, event):
        event.Skip()
        self.position_activity()
        self._utility = None
        self.remember_workspace()
        if self.legacy_tab() == 10:
            wx.CallAfter(self.unrouted.on_refresh)
        if self.legacy_tab() == 5 and not self.visualization.nets:
            wx.CallAfter(self.visualization.on_refresh)
        self.schedule_auto_refresh()

    def on_resize(self, event):
        event.Skip()
        wx.CallAfter(self.position_activity)

    def on_activate(self, event):
        event.Skip()
        if event.GetActive():
            if self.legacy_tab() == 10 and not self.actions_pending and not self.busy:
                wx.CallAfter(self.unrouted.on_refresh)
            self.schedule_auto_refresh()

    def schedule_auto_refresh(self):
        if self.auto_refresh_later:
            self.auto_refresh_later.Stop()
        if (
            not self.native_call
            or self.closing
            or self.legacy_tab() in (4, 5, 6, 7, 8, 9, 10, 11)
            or (self.legacy_tab() == 1 and self.via_tools.active_index >= 2)
            or (self.legacy_tab() == 3 and self.trace_tools.active_index != 0)
        ):
            return
        self.auto_refresh_later = wx.CallLater(350, self.check_board_revision)

    def check_board_revision(self):
        # Triggered by opening a tab or returning from PCB Editor, never a polling timer.
        if self.closing or wx.GetActiveWindow() not in (None, self):
            return
        if self.busy or self.actions_pending or self.change_check_pending:
            self.auto_check_deferred = True
            return
        self.auto_check_deferred = False
        tab = self.legacy_tab()
        if (
            tab in (4, 5, 6, 7, 8, 9, 10, 11)
            or (tab == 1 and self.via_tools.active_index >= 2)
            or (tab == 3 and self.trace_tools.active_index != 0)
        ):
            return
        via_mode = self.via_tools.active_index if tab == 1 else None
        trace_mode = self.trace_tools.active_index if tab == 3 else None
        page = (None, self.via_tools.active_page, self.fanout, self.trace_tools.active_page)[tab]
        policy_tab = (tab, via_mode) if tab == 1 else tab
        if page and getattr(page, "canvas", None) and getattr(page.canvas, "mode", None):
            return  # Never interrupt drawing a region.
        self.change_check_pending = True

        def done(state, error):
            self.change_check_pending = False
            if self.closing or error:
                if error and not self.closing:
                    if tab == 3:
                        self.trace_cleanup.message(
                            f"Board overview unavailable: {error}", "warning"
                        )
                    else:
                        self.snapshot.SetLabel(
                            "Automatic change check unavailable. Use Refresh (F5)."
                        )
                return  # No automatic retry after a busy/closed/old helper.
            self.resume_auto_check()
            if (
                self.legacy_tab() != tab
                or self.busy
                or self.actions_pending
                or (tab == 1 and self.via_tools.active_index != via_mode)
                or (tab == 3 and self.trace_tools.active_index != trace_mode)
            ):
                return
            if tab == 3:
                self.trace_cleanup.show_overview(state)
                return  # Opening Cleanup never starts a full scan.
            if self.refresh_policy.needs_refresh(policy_tab, state):
                if tab == 2 and not state["selection"]:
                    self.fanout.message(
                        "Select a BGA in PCB Editor, then return here to analyze it."
                    )
                    return
                self.on_refresh()

        def work():
            try:
                operation = "cleanup_info" if tab == 3 else "revision"
                state, error = self.api.call(lambda: self.native_call(operation)), None
            except Exception as exc:
                state, error = None, exc
            if not self.closing:
                wx.CallAfter(done, state, error)

        self.worker.submit(work)

    def resume_auto_check(self):
        if self.auto_check_deferred:
            self.auto_check_deferred = False
            self.schedule_auto_refresh()

    def on_activity_tick(self, _event):
        self.position_activity()
        self.activity.advance()

    def position_activity(self):
        if not self.activity_count or self.closing:
            return
        tab = self.legacy_tab()
        target = (
            self.tree.GetMainWindow()
            if tab == 0
            else self.via_array.table
            if tab == 1 and self.via_tools.active_index == 2
            else self.via_tools.pad_inspector.table
            if tab == 1 and self.via_tools.active_index == 4
            else self.via_tools.active_page.canvas
            if tab == 1
            else self.fanout.rows
            if tab == 2
            else self.trace_cleanup.table
            if tab == 3 and self.trace_tools.active_index == 0
            else self.trace_tools.teardrops.open_button
            if tab == 3 and self.trace_tools.active_index == 1
            else self.trace_tools.fillets.details
            if tab == 3
            else self.rotation.angle
            if tab == 4
            else self.visualization.group_list
            if tab == 5
            else self.unrouted.table
            if tab == 10
            else self.notebook.GetCurrentPage()
            if tab in (6, 8, 9, 11)
            else self.about
        )
        bounds = target.GetScreenRect()
        center = self.ScreenToClient((bounds.x + bounds.width // 2, bounds.y + bounds.height // 2))
        size = self.activity.GetSize()
        self.activity.SetPosition((center.x - size.width // 2, center.y - size.height // 2))
        self.activity.Raise()

    def begin_activity(self, label):
        self.activity_count += 1
        self.activity.set_message(label)
        if self.activity_count == 1:
            self.activity.Show()
            self.position_activity()
            self.activity_timer.Start(100)

    def end_activity(self):
        self.activity_count = max(0, self.activity_count - 1)
        if not self.activity_count:
            self.activity_timer.Stop()
            self.activity.Hide()

    def on_endpoints(self, event):
        if self.busy or self.actions_pending or self.closing:
            return
        from .endpoint_ui import EndpointDialog

        with EndpointDialog(self, self.endpoints) as dialog:
            dialog.ShowModal()

    # ----------------------------------------------------------- manual refresh (worker thread)
    def on_refresh(self, _event=None) -> None:
        if self.legacy_tab() == 11:
            self.components.on_refresh()
            return
        if self.legacy_tab() == 10:
            self.unrouted.on_refresh()
            return
        if self.legacy_tab() == 0:
            try:
                geometry = self.tools.routing_configuration()
                self.stackup_display.SetLabel(geometry.get('stackup', 'Stackup unavailable'))
                self.stackup_display.Wrap(max(400, self.GetClientSize().width - 40))
                self.routing_geometry.DeleteAllItems()
                for row in geometry.get('rows', []):
                    index = self.routing_geometry.InsertItem(self.routing_geometry.GetItemCount(),
                                                             str(row[0]))
                    for col, value in enumerate(row[1:], 1):
                        self.routing_geometry.SetItem(index, col, str(value))
                self.geometry_note.SetLabel(geometry.get('note', ''))
                self.geometry_note.Wrap(max(400, self.GetClientSize().width - 40))
                self.stackup_display.GetParent().Layout()
            except (OSError, ValueError, KeyError) as exc:
                self.stackup_display.SetLabel('Cannot read saved stackup: ' + str(exc))
                self.routing_geometry.DeleteAllItems()
        if self.legacy_tab() == 9:
            self.auto_text.on_refresh()
            return
        if self.legacy_tab() == 8:
            return
        if self.legacy_tab() == 6:
            return
        if self.legacy_tab() == 5:
            self.visualization.on_refresh()
            return
        if self.legacy_tab() == 4:
            self.rotation.on_refresh()
            return
        if self.legacy_tab() == 3:
            self.trace_tools.active_page.on_refresh()
            return
        if self.legacy_tab() == 2:
            self.fanout.on_refresh()
            return
        if self.legacy_tab() == 1:
            self.via_tools.active_page.on_refresh()
            return
        if self.busy or self.actions_pending or self.closing:
            return
        self.busy = True
        self.refresh.Disable()
        self.begin_activity("Reading signal lengths...")
        self.status.SetLabel("Refreshing timing from KiCad...")

        def work():
            logging.info("Refresh started")
            try:
                results, error = self.api.call(self.tools.evaluate, retries=0), None
                logging.info("Refresh completed")
            except Exception as exc:  # KiCad busy, closed or board switched
                logging.exception("Refresh failed")
                results, error = None, str(exc)
            if not self.closing:
                wx.CallAfter(self._apply, results, error)

        self.worker.submit(work)

    def _apply(self, results, error) -> None:
        self.busy = False
        self.end_activity()
        self.resume_auto_check()
        if self.closing:
            return
        self.refresh.Enable(not self.actions_pending)
        if error:
            self.status.SetForegroundColour(self.colors["warning"])
            self.status.SetLabel(
                f"Refresh failed: {error}. Previous values kept; click Refresh when KiCad is ready."
            )
            return
        self.status.SetForegroundColour(self.colors["pending"])
        self.results = results
        self.render()
        source = self.tools.source()
        when = wx.DateTime.Now().FormatTime()
        self.snapshot.SetLabel(
            f"Snapshot: {when}. Checks for changes when you return to TraceForge."
        )
        if not results:
            self.status.SetLabel(
                f"{when} · no signal chains found (no xsignals.json or nets "
                "assigned to tuning-profile netclasses)"
            )
        else:
            self.status.SetLabel(f"{when} · groups from {source}")

    def render(self) -> None:
        # Keep native row objects on timing refreshes: rebuilding them resets scrolling,
        # expansion and selection, and repaints the whole table unnecessarily.
        topology = tuple(
            (g.group.name, tuple((c.chain.name, c.chain.pair) for c in g.chains))
            for g in self.results
        )
        if topology == self.topology:
            self.update_rows()
            return
        main = self.tree.GetMainWindow()
        view = main.GetViewStart()
        self.tree.Freeze()
        try:
            if topology != self.topology:
                selected = self.selected_rows()
                expanded = {
                    name
                    for (name, chain), item in self.rows.items()
                    if chain is None and self.tree.IsExpanded(item)
                }
                first = self.topology is None
                self.tree.DeleteChildren(self.tree.GetRootItem())
                self.rows.clear()
                self.row_states.clear()
                for g in self.results:
                    key = (g.group.name, None)
                    gi = self.tree.AppendItem(self.tree.GetRootItem(), g.group.name)
                    self.tree.SetItemData(gi, key)
                    self.rows[key] = gi
                    self.tree.SetItemBold(gi, True)
                    for c in g.chains:
                        presentation = describe_signal(g.group, c.chain)
                        ci = self.tree.AppendItem(gi, presentation["label"])
                        self.tree.SetItemData(ci, (g.group.name, c.chain.name))
                        self.rows[g.group.name, c.chain.name] = ci
                    if first or g.group.name in expanded:
                        self.tree.Expand(gi)
                for key in selected:
                    if key in self.rows:
                        self.tree.SelectItem(self.rows[key])
                self.topology = topology
            self.update_rows()
            main.Scroll(*view)
        finally:
            self.tree.Thaw()

    def set_cells(self, item, cells) -> None:
        for col, text in cells:
            if self.tree.GetItemText(item, col) != text:
                self.tree.SetItemText(item, text, col)

    def set_row_state(self, key, state) -> None:
        if self.row_states.get(key) == state:
            return
        item = self.rows[key]
        self.tree.SetItemTextColour(item, wx.Colour(self.colors[state]))
        bg = (
            ("#40232C" if self.dark else "#FFF0F1")
            if state == "error"
            else ("#19212D" if self.dark else "#FFFFFF")
        )
        self.tree.SetItemBackgroundColour(item, wx.Colour(bg))
        self.row_states[key] = state

    def update_rows(self) -> None:
        counts = dict.fromkeys(self.colors, 0)
        fmt = lambda v, s=False: "" if v is None else (f"{v:+.1f}" if s else f"{v:.1f}")  # noqa: E731
        for g in self.results:
            key = (g.group.name, None)
            states = [self.chain_color(c, g) for c in g.chains]
            priority = ("error", "warning", "pending", "routed")
            state = next((k for k in priority if k in states), "ok")
            label = {
                "error": "\u2716 configured source-net limit exceeded",
                "warning": "\u25b2 needs tuning",
                "pending": "\u2026 pending",
                "routed": "\u25cf routed",
                "ok": "\u2714 matched",
            }[state]
            if any(c.status == "unprofiled" for c in g.chains):
                label = "\u2716 timing profile missing"
            self.set_cells(
                self.rows[key],
                ((2, fmt(g.target_ps)), (3, f"spread {fmt(g.spread_ps)}"), (6, label)),
            )
            self.set_row_state(key, state)
            for c in g.chains:
                key = (g.group.name, c.chain.name)
                status = f"{MARK.get(c.status, '')} {c.status}"
                if c.status == "unprofiled":
                    status = "\u2716 timing profile missing"
                if c.chain.name in g.stub_violations:
                    status = "\u2716 configured source-net limit exceeded"
                cells = (
                    fmt(c.total_ps) if c.timing_complete else "",
                    fmt(c.target_ps),
                    fmt(c.delta_ps, True) if c.timing_complete else "",
                    fmt(c.pair_skew_ps, True) if c.timing_complete else "",
                    fmt(c.stub_ps) if c.timing_complete else "",
                    status,
                    "" if c.length_mm is None else f"{c.length_mm:.3f}",
                    "" if c.tunable_mm is None else f"{c.tunable_mm:.3f}",
                    "" if c.stub_mm is None else f"{c.stub_mm:.3f}",
                )
                self.set_cells(self.rows[key], enumerate(cells, 1))
                state = self.chain_color(c, g)
                counts[state] += 1
                self.set_row_state(key, state)
        for key, chip in self.summary.items():
            label = f"\u25cf {key.title() if key != 'ok' else 'OK'}: {counts[key]}"
            if chip.GetLabel() != label:
                chip.SetLabel(label)

    def on_row_click(self, event) -> None:
        if self.busy or self.actions_pending or self.closing:
            event.Skip()
            return
        if event.ControlDown() or event.ShiftDown() or len(self.selected_rows()) > 1:
            event.Skip()
            return
        item, _flags, _column = self.tree.GetMainWindow().HitTest(event.GetPosition())
        if item and self.tree.GetItemParent(item) != self.tree.GetRootItem():
            group, chain = self.tree.GetItemData(item)
            self._run(lambda: f"highlighted {self.tools.highlight_chain(group, chain)} items")
        event.Skip()

    def on_signal_selection(self, event) -> None:
        group, chain = self.tree.GetItemData(event.GetItem()) or (None, None)
        definition = next((g.group for g in self.results if g.group.name == group), None)
        if definition is not None and chain is not None:
            member = next(c for c in definition.chains if c.name == chain)
            self.tuning_hint.SetLabel(describe_signal(definition, member)["hint"])
            self.tuning_hint.Wrap(1050)
            self.tuning_hint.GetParent().Layout()
        else:
            self.tuning_hint.SetLabel(
                "[DIFF]: KiCad 8 pair length / 9 P-N skew. [SE]: KiCad 7 single-track length."
            )
        event.Skip()

    @staticmethod
    def chain_color(chain, group) -> str:
        if chain.status == "unprofiled":
            return "error"
        if chain.chain.name in group.stub_violations:
            return "error"
        return {
            "ok": "ok",
            "short": "warning",
            "long": "warning",
            "pending": "pending",
            "routed": "routed",
        }.get(chain.status, "pending")

    # ----------------------------------------------------------- tools
    def selected_rows(self) -> list[tuple[str, Optional[str]]]:
        return [data for item in self.tree.GetSelections()
                if item and item != self.tree.GetRootItem()
                and (data := self.tree.GetItemData(item)) and data[0]]

    def selected(self) -> tuple[Optional[str], Optional[str]]:
        item = self.tree.GetFocusedItem()
        if item not in self.tree.GetSelections():
            items = self.tree.GetSelections()
            item = items[0] if items else None
        if not item or item == self.tree.GetRootItem():
            return None, None
        return self.tree.GetItemData(item) or (None, None)

    def _run(self, fn: Callable[[], str], background: bool = True) -> None:
        if self.closing:
            return
        if self.busy or self.actions_pending:
            self.status.SetLabel("An operation is already running; no additional request queued.")
            return
        if not background:  # Modal dialogs must stay on the wx UI thread.
            try:
                self.status.SetLabel(self.api.call(fn, retries=0))
            except Exception as exc:
                self._action_done(None, exc, decrement=False)
            return
        self.actions_pending += 1
        self.refresh.Disable()
        self.status.SetForegroundColour(self.colors["routed"])
        self.status.SetLabel("Selecting / working in KiCad...")
        self.begin_activity("Selecting / working in KiCad...")

        def work():
            logging.info("Panel action started")
            try:
                message, error = self.api.call(fn, retries=0), None
                logging.info("Panel action completed: %s", message)
            except Exception as exc:
                logging.exception("TraceForge action failed")
                message, error = None, exc
            if not self.closing:
                wx.CallAfter(self._action_done, message, error)

        self.worker.submit(work)

    def _action_done(self, message, error, decrement=True) -> None:
        self.resume_auto_check()
        if decrement:
            self.actions_pending -= 1
            self.end_activity()
        if self.closing:
            return
        self.refresh.Enable(not self.busy and not self.actions_pending)
        if error:
            self.status.SetForegroundColour(self.colors["error"])
            self.status.SetLabel(
                f"failed: {error}. If KiCad has an active tool or dialog, "
                "finish it or press Esc in PCB Editor, then retry."
            )
        else:
            self.status.SetForegroundColour(self.colors["routed"])
            self.status.SetLabel(message)

    def on_cancel_operation(self, event=None):
        if self.active_operation and self.active_operation[0].cancel():
            self.cancel_operation.Disable()
            self.active_operation[1].message('Cancellation requested; stopping at a safe boundary.',
                                             'warning')

    def submit_stitching(self, fn, done, page, cancellable=False):
        """Serialize board operations and coalesce deferred tab checks."""
        if self.closing:
            return
        if self.busy or self.actions_pending:
            page.message(
                "Another operation is running. No additional request was queued.", "warning"
            )
            return
        self.actions_pending += 1
        from .cancellation import Cancellation, OperationCancelled

        control = Cancellation() if cancellable else None
        if control:
            self.active_operation = (control, page)
            self.cancel_operation.Enable()
        self.refresh.Disable()
        self.begin_activity("Scanning / working in KiCad...")
        page.message(
            "Working in KiCad. Large previews and zone refill can take a moment.", "routed"
        )
        # Keep the canvas and findings visible instead of graying out the whole tab.
        # Freeze only editable inputs while a preview is based on their values.
        controls = []
        editable = (
            wx.Button,
            wx.TextCtrl,
            wx.Choice,
            wx.ComboBox,
            wx.CheckBox,
            wx.RadioButton,
            wx.SpinCtrl,
            wx.SpinCtrlDouble,
            wx.Slider,
            wx.ListBox,
        )
        pending = list(page.GetChildren())
        while pending:
            child = pending.pop()
            if isinstance(child, editable):
                controls.append((child, child.IsEnabled()))
                child.Disable()
            else:
                pending.extend(child.GetChildren())

        def finished(result, error):
            self.actions_pending -= 1
            if control:
                self.active_operation = None
                self.cancel_operation.Disable()
            self.end_activity()
            self.resume_auto_check()
            if self.closing:
                return
            for child, enabled in controls:
                if enabled and child:
                    child.Enable()
            self.refresh.Enable(not self.busy and not self.actions_pending)
            if isinstance(error, OperationCancelled) or (control and control.cancelled):
                page.invalidate()
                page.message('Cancelled. No board changes were applied.', 'pending')
            elif error:
                page.invalidate()
                page.message(str(error), "error")
            else:
                try:
                    done(result)
                except Exception as exc:
                    logging.exception("Board tool UI completion failed")
                    page.message(str(exc), "error")

        def work():
            try:
                def execute():
                    if control:
                        control.check()
                        value = fn(control)
                        control.check()
                        return value
                    return fn()

                result, error = self.api.call(execute, retries=0), None
            except Exception as exc:
                if not (control and control.cancelled):
                    logging.exception("Board tool operation failed")
                result, error = None, exc
            finally:
                if control:
                    control.close()
            if not self.closing:
                wx.CallAfter(finished, result, error)

        self.worker.submit(work)

    def on_chain(self, _=None) -> None:
        group, chain = self.selected()
        if group and chain:
            self._run(lambda: f"highlighted {self.tools.highlight_chain(group, chain)} items")
        else:
            self._run(lambda: self.tools.highlight_selection(False))

    def on_group(self, _=None) -> None:
        groups = list(dict.fromkeys(group for group, _chain in self.selected_rows()))
        if len(groups) > 1 and self.tools.highlight_groups:
            self._run(lambda: f"highlighted {self.tools.highlight_groups(groups)} items "
                      f"across {len(groups)} groups")
        elif len(groups) > 1:
            self.status.SetLabel(
                "Multiple-group highlighting requires the updated board callbacks."
            )
        elif groups:
            self._run(lambda: f"highlighted {self.tools.highlight_group(groups[0])} items")
        else:
            self._run(lambda: self.tools.highlight_selection(True))

    def on_clear(self, _=None) -> None:
        self._run(lambda: (self.tools.clear(), "selection cleared")[1])

    def on_zoom(self, _=None) -> None:
        self._run(self.tools.zoom_selection)

    def on_write(self, _=None) -> None:
        self._run(lambda: self.tools.write_targets(self.results))

    def on_export(self, _=None) -> None:
        self._run(self.tools.export_paths)

    def on_save(self, _=None) -> None:
        self._run(self.tools.save_config)

    def on_edit(self, _=None) -> None:
        if self.busy or self.actions_pending or self.closing:
            return
        self._run(lambda: self.tools.edit_chains(self), background=False)
        self.refresh_policy.invalidate(0)
        self.schedule_auto_refresh()
        self.snapshot.SetLabel("Chain editor closed. Click Refresh to update the timing table.")

    def on_overlay(self, _event) -> None:
        """Stay on top while KiCad or this panel is the active application."""

        if self.editor_pid is not None:
            if _kicad_pid(self.editor_pid) is None:
                self.missing_editor_checks += 1
                if self.missing_editor_checks >= 3 and not self.closing:
                    self.Close()
                return
            self.missing_editor_checks = 0
        if self.kicad_pid is None:
            self.kicad_pid = _kicad_pid()
        fg = _foreground_pid()
        want = fg is not None and fg in (self.kicad_pid, os.getpid())
        if want != self.on_top:
            style = self.GetWindowStyle()
            self.SetWindowStyle(style | wx.STAY_ON_TOP if want else style & ~wx.STAY_ON_TOP)
            self.on_top = want

    def on_shortcuts(self, _=None) -> None:
        dlg = ShortcutDialog(self, load_shortcuts())
        if dlg.ShowModal() == wx.ID_OK:
            values = dlg.values()
            bad = [k for k, v in values.items() if parse_shortcut(v) is None]
            if bad:
                names = ", ".join(LABELS[k] for k in bad)
                wx.MessageBox(f"Invalid shortcut: {names}", "TraceForge")
            else:
                save_shortcuts(values)
                self.register_shortcuts(values)
        dlg.Destroy()

    # ----------------------------------------------------------- shortcuts
    def register_shortcuts(self, shortcuts: dict[str, str]) -> None:
        for hid in list(self.hotkey_ids):
            self.UnregisterHotKey(hid)
        self.hotkey_ids.clear()
        failed = []
        for n, (action, text) in enumerate(shortcuts.items()):
            parsed = parse_shortcut(text)
            hid = 0xB000 + n
            if parsed and self.RegisterHotKey(hid, *parsed):
                self.hotkey_ids[hid] = action
            else:
                failed.append(f"{text} ({LABELS[action]})")
        if failed:
            self.status.SetLabel("shortcut already used by another program: " + "; ".join(failed))

    def on_hotkey(self, event: wx.KeyEvent) -> None:
        action = self.hotkey_ids.get(event.GetId())
        if action == "toggle_panel":
            self.Show(not self.IsShown())
            if self.IsShown():
                self.Raise()
            return
        pick = self.tools.highlight_selection
        handler = {
            "highlight_chain": lambda: self._run(lambda: pick(False)),
            "highlight_group": lambda: self._run(lambda: pick(True)),
            "clear": self.on_clear,
            "write_targets": self.on_write,
            "export_paths": self.on_export,
        }.get(action)
        if handler:
            self.activate_tool('signals.paths')
            handler()

    def on_close(self, event) -> None:
        if self.active_operation:
            self.active_operation[0].cancel()
        self.closing = True
        if self.auto_refresh_later:
            self.auto_refresh_later.Stop()
        self.overlay.Stop()
        self.activity_timer.Stop()
        self.components.shutdown()
        self.bom_cost.shutdown()
        self.worker.shutdown(wait=False, cancel_futures=True)
        for hid in list(self.hotkey_ids):
            self.UnregisterHotKey(hid)
        event.Skip()


def run(
    tools: Tools,
    single_instance_port: Optional[int] = None,
    stitching=None,
    endpoints=None,
    native_info=None,
    start_tab=None,
) -> None:
    app = wx.App(False)
    if kicad_dark_theme() and hasattr(app, "MSWEnableDarkMode"):
        app.MSWEnableDarkMode(1)  # wxWidgets 3.3 DarkMode_Always, matching KiCad's dark theme
    panel = TraceForgePanel(
        tools, stitching=stitching, endpoints=endpoints, native_info=native_info
    )
    if start_tab is not None:
        panel.activate_tool(start_tab)
    panel.Show()
    listener = None
    if single_instance_port is not None:
        from .single_instance import listen

        listener = listen(single_instance_port, lambda tab: wx.CallAfter(_bring_front, panel, tab))
    try:
        app.MainLoop()
    finally:
        if listener is not None:
            listener.stop()


def _bring_front(panel: wx.Frame, tab=None) -> None:
    if tab is not None:
        panel.activate_tool(tab)
    panel.Show()
    panel.Iconize(False)
    panel.Raise()
