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

from .api_access import ApiAccess
from .chains import GroupResult

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
MARK = {"ok": "✔", "short": "▲", "long": "▼", "pending": "…", "routed": "•"}


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


class BusyOverlay(wx.Panel):
    """Rotating loader centered over the active tab's main results area."""

    def __init__(self, parent, dark):
        super().__init__(parent, size=(250, 132))
        self.dark = dark
        self.phase = 0
        self.message = 'Scanning board...'
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
        background = wx.Colour('#253449' if self.dark else '#F4F8FC')
        border = wx.Colour('#59748E' if self.dark else '#A8BED1')
        primary = wx.Colour('#7DCFFF' if self.dark else '#145FA0')
        dim = wx.Colour('#39536E' if self.dark else '#B2CBDD')
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        dc.SetPen(wx.Pen(border, 1))
        dc.SetBrush(wx.Brush(background))
        dc.DrawRoundedRectangle(1, 1, size.width - 2, size.height - 2, 10)
        dc.SetPen(wx.TRANSPARENT_PEN)
        for index in range(12):
            strength = (12 - (index - self.phase) % 12) / 12
            color = wx.Colour(*(
                round(a + strength * (b - a))
                for a, b in zip((dim.Red(), dim.Green(), dim.Blue()),
                                (primary.Red(), primary.Green(), primary.Blue()))))
            dc.SetBrush(wx.Brush(color))
            angle = 2 * math.pi * index / 12 - math.pi / 2
            dc.DrawCircle(round(size.width / 2 + 24 * math.cos(angle)),
                          round(52 + 24 * math.sin(angle)), 4)
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


def _kicad_pid() -> Optional[int]:
    """Process id of the KiCad PCB editor window (Windows only)."""

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

    def __init__(self, tools: Tools, stitching=None, endpoints=None):
        style = wx.DEFAULT_FRAME_STYLE | wx.FRAME_TOOL_WINDOW
        super().__init__(None, title="TraceForge", size=(1160, 520), style=style)
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
        self.kicad_pid, self.on_top = _kicad_pid(), False
        self.overlay = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_overlay, self.overlay)
        self.overlay.Start(400)

        self.dark = kicad_dark_theme()
        self.colors = ({"ok": "#6EE7A0", "warning": "#FFD166", "error": "#FF8585",
                        "pending": "#A8B4C7", "routed": "#7DCFFF"} if self.dark else
                       {"ok": "#136C3B", "warning": "#895100", "error": "#B42332",
                        "pending": "#586477", "routed": "#145FA0"})
        icon = Path(__file__).resolve().parents[1] / "icons" / (
            "traceforge-dark-48.png" if self.dark else "traceforge-light-48.png")
        self.SetIcon(wx.Icon(str(icon), wx.BITMAP_TYPE_PNG))
        self.notebook = wx.Notebook(self)
        root = wx.Panel(self.notebook)
        if self.dark:
            root.SetBackgroundColour("#222C3A")
            root.SetForegroundColour("#E5EDF8")
        bar = wx.BoxSizer(wx.HORIZONTAL)
        buttons = (("Highlight chain", self.on_chain), ("Highlight group", self.on_group),
                   ("Zoom selection", self.on_zoom),
                   ("Clear", self.on_clear), ("Write DRC targets", self.on_write),
                   ("Export paths", self.on_export), ("Chain editor…", self.on_edit),
                   ("Shortcuts…", self.on_shortcuts))
        for label, handler in buttons:
            btn = wx.Button(root, label=label, style=wx.BU_EXACTFIT)
            btn.Bind(wx.EVT_BUTTON, handler)
            bar.Add(btn, 0, wx.RIGHT, 4)
        self.refresh = wx.Button(root, label="Refresh (F5)", style=wx.BU_EXACTFIT)
        self.refresh.SetToolTip('Force refresh. Tabs also refresh when opened or revisited '
                               'after a board change. No continuous polling.')
        self.refresh.Bind(wx.EVT_BUTTON, self.on_refresh)
        bar.AddStretchSpacer()
        bar.Add(self.refresh)
        refresh_id = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self.on_refresh, id=refresh_id)
        self.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_NORMAL, wx.WXK_F5, refresh_id)]))

        self.tree = htl.HyperTreeList(root, agwStyle=(wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS |
                                                    wx.TR_FULL_ROW_HIGHLIGHT | wx.TR_LINES_AT_ROOT))
        if self.dark:
            self.tree.SetBackgroundColour("#19212D")
            self.tree.SetForegroundColour("#E5EDF8")
        right = wx.ALIGN_RIGHT
        columns = (("Group / chain", 190, wx.ALIGN_LEFT), ("Total ps", 80, right),
                   ("Target ps", 80, right), ("Δ ps", 70, right), ("P−N ps", 70, right),
                   ("Stub ps", 70, right), ("Status", 160, wx.ALIGN_LEFT),
                   ("Chain track mm", 110, right), ("Tunable mm", 100, right),
                   ("Stub mm", 85, right))
        for title, width, align in columns:
            self.tree.AddColumn(title, width=width, flag=align)
        self.tree.AddRoot("signals")
        self.rows = {}
        self.row_states = {}
        self.topology = None
        self.tree.GetMainWindow().Bind(wx.EVT_LEFT_UP, self.on_row_click)
        self.status = wx.StaticText(root, label="Click Refresh to load timing from KiCad.")
        self.snapshot = wx.StaticText(root, label="No timing snapshot yet. Manual refresh only.")
        self.snapshot.SetForegroundColour(self.colors["pending"])
        self.tree.GetMainWindow().SetToolTip(
            "Chain track mm = all tracks and arcs across every net in the chain. "
            "Tunable mm = last net; Stub mm = first net before series parts. "
            "Lengths exclude via barrels, pad-to-die lengths, and component internals. "
            "All net branches are summed; KiCad tunes a point-to-point path. "
            "Timing includes the configured via and pad-to-die delay estimates.")
        self.status.SetForegroundColour(self.colors["pending"])

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
        detect = wx.Button(root, label='Detect path between 2 selected PCB items...')
        detect.Enable(endpoints is not None)
        detect.Bind(wx.EVT_BUTTON, self.on_endpoints)
        box.Add(detect, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        legend = wx.BoxSizer(wx.HORIZONTAL)
        self.summary = {}
        for key, label in (("ok", "OK"), ("warning", "Warning"), ("error", "Error"),
                           ("pending", "Pending"), ("routed", "Routed")):
            chip = wx.StaticText(root, label=f"\u25cf {label}: 0")
            chip.SetForegroundColour(self.colors[key])
            chip.SetFont(chip.GetFont().Bold())
            self.summary[key] = chip
            legend.Add(chip, 0, wx.RIGHT, 18)
        box.Add(legend, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        box.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        box.Add(self.snapshot, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        box.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        root.SetSizer(box)

        from .stitching_ui import StitchingPanel

        self.notebook.AddPage(root, 'Signals / xSignals')
        self.stitching = StitchingPanel(self.notebook, self, stitching)
        self.notebook.AddPage(self.stitching, 'Via Stitching')
        from .fanout_ui import FanoutPanel

        self.fanout = FanoutPanel(self.notebook, self, stitching)
        self.notebook.AddPage(self.fanout, 'BGA Fanout')
        from .trace_fence_ui import TraceFencePanel

        self.trace_fence = TraceFencePanel(self.notebook, self, stitching)
        self.notebook.AddPage(self.trace_fence, 'Via Fencing')
        from .trace_cleanup_ui import TraceCleanupPanel

        self.trace_cleanup = TraceCleanupPanel(self.notebook, self, stitching)
        self.notebook.AddPage(self.trace_cleanup, 'Trace Cleanup')
        if self.dark:
            self.stitching.SetBackgroundColour('#222C3A')
            self.stitching.SetForegroundColour('#E5EDF8')
        frame_box = wx.BoxSizer(wx.VERTICAL)
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
        wx.CallAfter(self.schedule_auto_refresh)

    def on_tab_open(self, event):
        event.Skip()
        self.position_activity()
        self.schedule_auto_refresh()

    def on_resize(self, event):
        event.Skip()
        wx.CallAfter(self.position_activity)

    def on_activate(self, event):
        event.Skip()
        if event.GetActive():
            self.schedule_auto_refresh()

    def schedule_auto_refresh(self):
        if not self.native_call or self.closing:
            return
        if self.auto_refresh_later:
            self.auto_refresh_later.Stop()
        self.auto_refresh_later = wx.CallLater(350, self.check_board_revision)

    def check_board_revision(self):
        # Triggered by opening a tab or returning from PCB Editor, never a polling timer.
        if self.closing or wx.GetActiveWindow() not in (None, self):
            return
        if self.busy or self.actions_pending or self.change_check_pending:
            self.auto_check_deferred = True
            return
        self.auto_check_deferred = False
        tab = self.notebook.GetSelection()
        page = (None, self.stitching, self.fanout, self.trace_fence, self.trace_cleanup)[tab]
        if page and getattr(page, 'canvas', None) and getattr(page.canvas, 'mode', None):
            return  # Never interrupt drawing a region.
        self.change_check_pending = True

        def done(state, error):
            self.change_check_pending = False
            if self.closing or error:
                if error and not self.closing:
                    if tab == 4:
                        self.trace_cleanup.message(
                            f'Board overview unavailable: {error}', 'warning')
                    else:
                        self.snapshot.SetLabel(
                            'Automatic change check unavailable. Use Refresh (F5).')
                return  # No automatic retry after a busy/closed/old helper.
            self.resume_auto_check()
            if (self.notebook.GetSelection() != tab or self.busy or self.actions_pending):
                return
            if tab == 4:
                self.trace_cleanup.show_overview(state)
                return  # Opening Cleanup never starts a full scan.
            if self.refresh_policy.needs_refresh(tab, state):
                if tab == 2 and not state['selection']:
                    self.fanout.message('Select a BGA in PCB Editor, then return here '
                                        'to analyze it.')
                    return
                self.on_refresh()

        def work():
            try:
                operation = 'cleanup_info' if tab == 4 else 'revision'
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
        tab = self.notebook.GetSelection()
        target = (self.tree.GetMainWindow() if tab == 0 else
                  self.trace_cleanup.table if tab == 4 else
                  self.notebook.GetPage(tab).canvas)
        bounds = target.GetScreenRect()
        center = self.ScreenToClient((bounds.x + bounds.width // 2,
                                      bounds.y + bounds.height // 2))
        size = self.activity.GetSize()
        self.activity.SetPosition((center.x - size.width // 2,
                                   center.y - size.height // 2))
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
        if self.notebook.GetSelection() == 4:
            self.trace_cleanup.on_refresh()
            return
        if self.notebook.GetSelection() == 3:
            self.trace_fence.on_refresh()
            return
        if self.notebook.GetSelection() == 2:
            self.fanout.on_refresh()
            return
        if self.notebook.GetSelection() == 1:
            self.stitching.on_refresh()
            return
        if self.busy or self.actions_pending or self.closing:
            return
        self.busy = True
        self.refresh.Disable()
        self.begin_activity('Reading signal lengths...')
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
            self.status.SetLabel(f"Refresh failed: {error}. Previous values kept; click Refresh "
                                 "when KiCad is ready.")
            return
        self.status.SetForegroundColour(self.colors["pending"])
        self.results = results
        self.render()
        source = self.tools.source()
        when = wx.DateTime.Now().FormatTime()
        self.snapshot.SetLabel(f"Snapshot: {when}. Checks for changes when you return "
                               'to TraceForge.')
        if not results:
            self.status.SetLabel(f"{when} · no signal chains found (no xsignals.json and no series "
                                 "parts between tuning-profile netclasses)")
        else:
            self.status.SetLabel(f"{when} · groups from {source}")

    def render(self) -> None:
        # Keep native row objects on timing refreshes: rebuilding them resets scrolling,
        # expansion and selection, and repaints the whole table unnecessarily.
        topology = tuple((g.group.name, tuple(c.chain.name for c in g.chains))
                         for g in self.results)
        if topology == self.topology:
            self.update_rows()
            return
        main = self.tree.GetMainWindow()
        view = main.GetViewStart()
        self.tree.Freeze()
        try:
            if topology != self.topology:
                selected = self.selected()
                expanded = {name for (name, chain), item in self.rows.items()
                            if chain is None and self.tree.IsExpanded(item)}
                first = self.topology is None
                self.tree.DeleteChildren(self.tree.GetRootItem())
                self.rows.clear()
                self.row_states.clear()
                for g in self.results:
                    key = (g.group.name, None)
                    gi = self.tree.AppendItem(self.tree.GetRootItem(), g.group.name)
                    self.rows[key] = gi
                    self.tree.SetItemBold(gi, True)
                    for c in g.chains:
                        ci = self.tree.AppendItem(gi, c.chain.name)
                        self.rows[g.group.name, c.chain.name] = ci
                    if first or g.group.name in expanded:
                        self.tree.Expand(gi)
                if selected in self.rows:
                    self.tree.SelectItem(self.rows[selected])
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
        bg = ("#40232C" if self.dark else "#FFF0F1") if state == "error" else (
            "#19212D" if self.dark else "#FFFFFF")
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
            label = {"error": "\u2716 stub too long", "warning": "\u25b2 needs tuning",
                     "pending": "\u2026 pending", "routed": "\u25cf routed",
                     "ok": "\u2714 matched"}[state]
            self.set_cells(self.rows[key], ((2, fmt(g.target_ps)),
                           (3, f"spread {fmt(g.spread_ps)}"), (6, label)))
            self.set_row_state(key, state)
            for c in g.chains:
                key = (g.group.name, c.chain.name)
                status = f"{MARK.get(c.status, '')} {c.status}"
                if c.chain.name in g.stub_violations:
                    status = "\u2716 stub too long"
                cells = (fmt(c.total_ps), fmt(c.target_ps), fmt(c.delta_ps, True),
                         fmt(c.pair_skew_ps, True), fmt(c.stub_ps), status,
                         "" if c.length_mm is None else f"{c.length_mm:.3f}",
                         "" if c.tunable_mm is None else f"{c.tunable_mm:.3f}",
                         "" if c.stub_mm is None else f"{c.stub_mm:.3f}")
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
        item, _flags, _column = self.tree.GetMainWindow().HitTest(event.GetPosition())
        if item and self.tree.GetItemParent(item) != self.tree.GetRootItem():
            group = self.tree.GetItemText(self.tree.GetItemParent(item))
            chain = self.tree.GetItemText(item)
            self.tree.SelectItem(item)
            self._run(lambda: f"highlighted {self.tools.highlight_chain(group, chain)} items")
        event.Skip()

    @staticmethod
    def chain_color(chain, group) -> str:
        if chain.chain.name in group.stub_violations:
            return "error"
        return {"ok": "ok", "short": "warning", "long": "warning",
                "pending": "pending", "routed": "routed"}.get(chain.status, "pending")

    # ----------------------------------------------------------- tools
    def selected(self) -> tuple[Optional[str], Optional[str]]:
        item = self.tree.GetSelection()
        if not item or item == self.tree.GetRootItem():
            return None, None
        parent = self.tree.GetItemParent(item)
        if parent == self.tree.GetRootItem():
            return self.tree.GetItemText(item), None
        return self.tree.GetItemText(parent), self.tree.GetItemText(item)

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
        if self.closing:
            return
        self.refresh.Enable(not self.busy and not self.actions_pending)
        if error:
            self.status.SetForegroundColour(self.colors["error"])
            self.status.SetLabel(f"failed: {error}. If KiCad has an active tool or dialog, "
                                 "finish it or press Esc in PCB Editor, then retry.")
        else:
            self.status.SetForegroundColour(self.colors["routed"])
            self.status.SetLabel(message)

    def submit_stitching(self, fn, done, page):
        """Serialize board operations and coalesce deferred tab checks."""
        if self.closing:
            return
        if self.busy or self.actions_pending:
            page.message('Another operation is running. No additional request was queued.',
                         'warning')
            return
        self.actions_pending += 1
        self.refresh.Disable()
        self.begin_activity('Scanning / working in KiCad...')
        page.message('Working in KiCad. Large previews and zone refill can take a moment.',
                     'routed')
        # Keep the canvas and findings visible instead of graying out the whole tab.
        # Freeze only editable inputs while a preview is based on their values.
        controls = []
        editable = (wx.Button, wx.TextCtrl, wx.Choice, wx.ComboBox, wx.CheckBox,
                    wx.RadioButton, wx.SpinCtrl, wx.SpinCtrlDouble, wx.Slider,
                    wx.ListBox)
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
            self.end_activity()
            self.resume_auto_check()
            if self.closing:
                return
            for child, enabled in controls:
                if enabled and child:
                    child.Enable()
            self.refresh.Enable(not self.busy and not self.actions_pending)
            if error:
                page.invalidate()
                page.message(str(error), 'error')
            else:
                try:
                    done(result)
                except Exception as exc:
                    logging.exception('Board tool UI completion failed')
                    page.message(str(exc), 'error')

        def work():
            try:
                result, error = self.api.call(fn, retries=0), None
            except Exception as exc:
                logging.exception('Board tool operation failed')
                result, error = None, exc
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
        group, _chain = self.selected()
        if group:
            self._run(lambda: f"highlighted {self.tools.highlight_group(group)} items")
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
        handler = {"highlight_chain": lambda: self._run(lambda: pick(False)),
                   "highlight_group": lambda: self._run(lambda: pick(True)),
                   "clear": self.on_clear, "write_targets": self.on_write,
                   "export_paths": self.on_export}.get(action)
        if handler:
            self.notebook.ChangeSelection(0)
            handler()

    def on_close(self, event) -> None:
        self.closing = True
        if self.auto_refresh_later:
            self.auto_refresh_later.Stop()
        self.overlay.Stop()
        self.activity_timer.Stop()
        self.worker.shutdown(wait=False, cancel_futures=True)
        for hid in list(self.hotkey_ids):
            self.UnregisterHotKey(hid)
        event.Skip()


def run(tools: Tools, single_instance_port: Optional[int] = None, stitching=None,
        endpoints=None) -> None:
    app = wx.App(False)
    if kicad_dark_theme() and hasattr(app, "MSWEnableDarkMode"):
        app.MSWEnableDarkMode(1)  # wxWidgets 3.3 DarkMode_Always, matching KiCad's dark theme
    panel = TraceForgePanel(tools, stitching=stitching, endpoints=endpoints)
    panel.Show()
    listener = None
    if single_instance_port is not None:
        from .single_instance import listen

        listener = listen(single_instance_port, lambda: wx.CallAfter(_bring_front, panel))
    try:
        app.MainLoop()
    finally:
        if listener is not None:
            listener.stop()


def _bring_front(panel: wx.Frame) -> None:
    panel.Show()
    panel.Iconize(False)
    panel.Raise()
