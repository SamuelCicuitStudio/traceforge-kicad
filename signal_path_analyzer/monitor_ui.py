"""Live net-chain monitor window (tkinter, standard library only)."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .chains import GroupResult

COLUMNS = ("total", "target", "delta", "pair", "stub", "status")
HEAD = {"total": "Total ps", "target": "Target ps", "delta": "Δ ps", "pair": "P-N ps",
        "stub": "Stub ps", "status": "Status"}
COLORS = {"ok": "#1b7f3b", "short": "#b26a00", "long": "#b26a00", "pending": "#7a7a7a",
          "routed": "#1f4e9a", "stub": "#c62828"}


def _fmt(v: Optional[float], sign: bool = False) -> str:
    if v is None:
        return ""
    return f"{v:+.1f}" if sign else f"{v:.1f}"


class MonitorWindow:
    """Shows group/chain timing; the caller supplies callbacks bound to the live board."""

    def __init__(self, evaluate: Callable[[], list[GroupResult]],
                 highlight_chain: Callable[[str, str], int],
                 highlight_group: Callable[[str], int], clear: Callable[[], None],
                 write_targets: Callable[[list[GroupResult]], str], period_ms: int = 1000):
        self.evaluate = evaluate
        self.highlight_chain, self.highlight_group = highlight_chain, highlight_group
        self.clear, self.write_targets, self.period = clear, write_targets, period_ms
        self.paused, self.results = False, []
        self.root = tk.Tk()
        self.root.title("TraceForge - Signal Timing Monitor")
        self.root.attributes("-topmost", True)
        bar = ttk.Frame(self.root)
        bar.pack(fill="x")
        for text, cmd in (("Highlight chain", self._hl_chain), ("Highlight group", self._hl_group),
                          ("Clear", self._clear), ("Write DRC targets", self._write),
                          ("Pause", self._pause)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2, pady=2)
        self.tree = ttk.Treeview(self.root, columns=COLUMNS, height=24)
        self.tree.heading("#0", text="Group / chain")
        self.tree.column("#0", width=210)
        for c in COLUMNS:
            self.tree.heading(c, text=HEAD[c])
            self.tree.column(c, width=78, anchor="e")
        for tag, color in COLORS.items():
            self.tree.tag_configure(tag, foreground=color)
        self.tree.pack(fill="both", expand=True)
        self.status = ttk.Label(self.root, anchor="w")
        self.status.pack(fill="x")
        self.open_groups: set[str] = set()

    # -------------------------------------------------------------- refresh
    def _refresh(self) -> None:
        if not self.paused:
            t0 = time.perf_counter()
            try:
                self.results = self.evaluate()
                self._render()
                self.status.config(text=f"updated {time.strftime('%H:%M:%S')} "
                                        f"({(time.perf_counter() - t0) * 1000:.0f} ms)")
            except Exception as exc:  # KiCad closed, board switched, IPC timeout
                self.status.config(text=f"waiting for KiCad: {exc}")
        self.root.after(self.period, self._refresh)

    def _render(self) -> None:
        for gid in self.tree.get_children():
            if self.tree.item(gid, "open"):
                self.open_groups.add(gid)
        self.tree.delete(*self.tree.get_children())
        for g in self.results:
            gid = g.group.name
            spread = g.spread_ps
            gtag = "stub" if g.stub_violations else ("ok" if all(
                c.status in ("ok", "routed") for c in g.chains) else "pending")
            stub_note = f"stub! {len(g.stub_violations)}" if g.stub_violations else ""
            self.tree.insert("", "end", iid=gid, text=gid, open=gid in self.open_groups,
                             values=("", _fmt(g.target_ps), f"spread {_fmt(spread)}", "", "",
                                     stub_note),
                             tags=(gtag,))
            for c in g.chains:
                stub_bad = c.chain.name in g.stub_violations
                values = (_fmt(c.total_ps), _fmt(c.target_ps), _fmt(c.delta_ps, True),
                          _fmt(c.pair_skew_ps, True), _fmt(c.stub_ps), c.status)
                self.tree.insert(gid, "end", iid=f"{gid}\t{c.chain.name}", text=c.chain.name,
                                 values=values, tags=("stub" if stub_bad else c.status,))

    # -------------------------------------------------------------- buttons
    def _selected(self) -> tuple[Optional[str], Optional[str]]:
        sel = self.tree.selection()
        if not sel:
            return None, None
        parts = sel[0].split("\t")
        return parts[0], parts[1] if len(parts) > 1 else None

    def _hl_chain(self) -> None:
        group, chain = self._selected()
        if group and chain:
            self.status.config(text=f"highlighted {self.highlight_chain(group, chain)} items")

    def _hl_group(self) -> None:
        group, _ = self._selected()
        if group:
            self.status.config(text=f"highlighted {self.highlight_group(group)} items")

    def _clear(self) -> None:
        self.clear()

    def _write(self) -> None:
        self.status.config(text=self.write_targets(self.results))

    def _pause(self) -> None:
        self.paused = not self.paused
        self.status.config(text="paused" if self.paused else "resumed")

    def run(self) -> None:
        self._refresh()
        self.root.mainloop()
