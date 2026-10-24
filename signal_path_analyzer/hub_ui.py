"""TraceForge panel: one floating window over the KiCad PCB editor with every TraceForge tool.

wxPython is available in KiCad's plugin environments (created with --system-site-packages), so
the panel uses the same toolkit as KiCad. On Windows the panel is owned by the PCB editor window:
it stays above KiCad, minimises with it, and does not float over other applications.
Shortcuts are registered by the panel itself and work while KiCad (or the panel) has focus.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import wx
import wx.dataview as dv

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
# wx TreeListCtrl has no per-row colours, so status carries a symbol
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
    """Floating TraceForge window: live signal timing plus every tool."""

    def __init__(self, tools: Tools, period_ms: int = 1000):
        style = wx.DEFAULT_FRAME_STYLE | wx.FRAME_TOOL_WINDOW
        super().__init__(None, title="TraceForge", size=(840, 520), style=style)
        self.tools, self.period, self.results = tools, period_ms, []
        self.paused, self.busy, self.open_groups = False, False, set()
        self.hotkey_ids: dict[int, str] = {}
        self.SetMinSize((520, 260))
        # Overlay: on top only while KiCad (or this panel) is the active application. A
        # cross-process window owner is avoided on purpose; Windows can hang or misbehave with it.
        self.kicad_pid, self.on_top = _kicad_pid(), False
        self.overlay = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_overlay, self.overlay)
        self.overlay.Start(400)

        root = wx.Panel(self)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        buttons = (("Highlight chain", self.on_chain), ("Highlight group", self.on_group),
                   ("Clear", self.on_clear), ("Write DRC targets", self.on_write),
                   ("Export paths", self.on_export), ("Save config", self.on_save),
                   ("Shortcuts…", self.on_shortcuts))
        for label, handler in buttons:
            btn = wx.Button(root, label=label, style=wx.BU_EXACTFIT)
            btn.Bind(wx.EVT_BUTTON, handler)
            bar.Add(btn, 0, wx.RIGHT, 4)
        self.pause = wx.ToggleButton(root, label="Pause", style=wx.BU_EXACTFIT)
        self.pause.Bind(wx.EVT_TOGGLEBUTTON, lambda e: setattr(self, "paused", e.IsChecked()))
        bar.AddStretchSpacer()
        bar.Add(self.pause)

        self.tree = dv.TreeListCtrl(root, style=dv.TL_SINGLE)
        right = wx.ALIGN_RIGHT
        columns = (("Group / chain", 190, wx.ALIGN_LEFT), ("Total ps", 80, right),
                   ("Target ps", 80, right), ("Δ ps", 70, right), ("P−N ps", 70, right),
                   ("Stub ps", 70, right), ("Status", 160, wx.ALIGN_LEFT))
        for title, width, align in columns:
            self.tree.AppendColumn(title, width=width, align=align)
        self.status = wx.StaticText(root, label="starting…")

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(bar, 0, wx.EXPAND | wx.ALL, 6)
        box.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        box.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        root.SetSizer(box)

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.Bind(wx.EVT_HOTKEY, self.on_hotkey)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.register_shortcuts(load_shortcuts())
        self.timer.Start(self.period)
        self.on_timer(None)

    # ----------------------------------------------------------- live refresh (worker thread)
    def on_timer(self, _event) -> None:
        if self.paused or self.busy:
            return
        self.busy = True

        def work():
            try:
                results, error = self.tools.evaluate(), None
            except Exception as exc:  # KiCad busy, closed or board switched
                results, error = None, str(exc)
            wx.CallAfter(self._apply, results, error)

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, results, error) -> None:
        self.busy = False
        if error:
            self.status.SetLabel(f"waiting for KiCad: {error}")
            return
        self.results = results
        self.render()
        source = self.tools.source()
        when = wx.DateTime.Now().FormatTime()
        if not results:
            self.status.SetLabel(f"{when} · no signal chains found (no xsignals.json and no series "
                                 "parts between tuning-profile netclasses)")
        else:
            self.status.SetLabel(f"{when} · groups from {source}")

    def render(self) -> None:
        item = self.tree.GetFirstChild(self.tree.GetRootItem())
        while item.IsOk():
            if self.tree.IsExpanded(item):
                self.open_groups.add(self.tree.GetItemText(item))
            else:
                self.open_groups.discard(self.tree.GetItemText(item))
            item = self.tree.GetNextSibling(item)
        selected = self.selected()
        self.tree.DeleteAllItems()
        fmt = lambda v, s=False: "" if v is None else (f"{v:+.1f}" if s else f"{v:.1f}")  # noqa: E731
        for g in self.results:
            gi = self.tree.AppendItem(self.tree.GetRootItem(), g.group.name)
            self.tree.SetItemText(gi, 2, fmt(g.target_ps))
            self.tree.SetItemText(gi, 3, f"spread {fmt(g.spread_ps)}")
            if g.stub_violations:
                self.tree.SetItemText(gi, 6, f"✖ {len(g.stub_violations)} stub too long")
            else:
                done = all(c.status in ("ok", "routed") for c in g.chains)
                self.tree.SetItemText(gi, 6, "✔ matched" if done else "")
            for c in g.chains:
                ci = self.tree.AppendItem(gi, c.chain.name)
                status = f"{MARK.get(c.status, '')} {c.status}"
                if c.chain.name in g.stub_violations:
                    status += "  ✖ stub too long"
                cells = (fmt(c.total_ps), fmt(c.target_ps), fmt(c.delta_ps, True),
                         fmt(c.pair_skew_ps, True), fmt(c.stub_ps), status)
                for col, text in enumerate(cells, 1):
                    self.tree.SetItemText(ci, col, text)
                if selected == (g.group.name, c.chain.name):
                    self.tree.Select(ci)
            if g.group.name in self.open_groups or not self.open_groups:
                self.tree.Expand(gi)

    # ----------------------------------------------------------- tools
    def selected(self) -> tuple[Optional[str], Optional[str]]:
        item = self.tree.GetSelection()
        if not item.IsOk():
            return None, None
        parent = self.tree.GetItemParent(item)
        if parent == self.tree.GetRootItem():
            return self.tree.GetItemText(item), None
        return self.tree.GetItemText(parent), self.tree.GetItemText(item)

    def _run(self, fn: Callable[[], str]) -> None:
        try:
            self.status.SetLabel(fn())
        except Exception as exc:
            self.status.SetLabel(f"failed: {exc}")

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

    def on_write(self, _=None) -> None:
        self._run(lambda: self.tools.write_targets(self.results))

    def on_export(self, _=None) -> None:
        self._run(self.tools.export_paths)

    def on_save(self, _=None) -> None:
        self._run(self.tools.save_config)

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
            handler()

    def on_close(self, event) -> None:
        self.timer.Stop()
        self.overlay.Stop()
        for hid in list(self.hotkey_ids):
            self.UnregisterHotKey(hid)
        event.Skip()


def run(tools: Tools, single_instance_port: Optional[int] = None) -> None:
    app = wx.App(False)
    if kicad_dark_theme() and hasattr(app, "MSWEnableDarkMode"):
        app.MSWEnableDarkMode(1)  # wxWidgets 3.3 DarkMode_Always, matching KiCad's dark theme
    panel = TraceForgePanel(tools)
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
