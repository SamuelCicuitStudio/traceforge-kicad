"""Signal Chain Editor (wx): create, review and group signal chains like Altium xSignals.

1. Enter or pick (from the KiCad selection) source/driver and destination components, then Find.
   Chains are traced through series parts; the driver side is inferred from placement.
2. Review: keep/untick chains, rename their group (edit the Group cell).
3. Set each group's skew / pair skew / stub limits, then Apply & save. The result is stored in
   <board>.traceforge.json and the live timing table uses it immediately.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import wx
import wx.dataview as dv
import wx.grid as gridlib

from .chains import Config, GroupDef
from .pathfinder import (
    DEFAULT_LIMITS,
    FoundChain,
    GroupSuggestion,
    _group_for,
    merge_into,
    name_and_group,
)

COLS = ("Keep", "Chain", "Group", "Pair", "Path (driver → receiver)", "Series")


def _short(net: str) -> str:
    return net.rstrip("/").split("/")[-1]


def chains_from_config(config: Optional[Config]) -> list[FoundChain]:
    out = []
    for g in config.groups if config else []:
        for c in g.chains:
            out.append(FoundChain(c.name, c.nets, c.series, "", "", g.name, c.pair, True))
    return out


class ChainEditor(wx.Dialog):
    def __init__(self, parent: Optional[wx.Window], config: Optional[Config],
                 find: Callable[[list[str], list[str], float, bool], list[FoundChain]],
                 selection: Callable[[], list[str]], detect_selected=None, selection_items=None,
                 pick_endpoint=None):
        super().__init__(parent, title="TraceForge · Signal Chain Editor", size=(1100, 720),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.find, self.selection = find, selection
        self.detect_selected = detect_selected
        self.selection_items = selection_items
        self.pick_endpoint = pick_endpoint
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chain-editor')
        self.working, self.closed = False, False
        self.chains: list[FoundChain] = chains_from_config(config)
        self.limits: dict[str, tuple] = {g.name: (g.skew_ps, g.pair_skew_ps, g.stub_max_ps)
                                         for g in (config.groups if config else [])}
        self.die = config.pad_to_die_ps_per_mm if config else 6.952

        # ---- create between components
        top = wx.FlexGridSizer(cols=4, vgap=4, hgap=6)
        self.src = wx.TextCtrl(self, size=(260, -1))
        self.dst = wx.TextCtrl(self, size=(260, -1))
        for label, field in (("Source (driver) parts", self.src), ("Destination parts", self.dst)):
            top.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            top.Add(field, 1, wx.EXPAND)
            btn = wx.Button(self, label="Use KiCad selection")
            btn.Bind(wx.EVT_BUTTON, lambda _e, f=field: self.use_selection(f))
            top.Add(btn)
            top.Add((0, 0))
        opts = wx.BoxSizer(wx.HORIZONTAL)
        self.ohms = wx.SpinCtrlDouble(self, min=0, max=1000, initial=100, inc=1, size=(80, -1))
        self.caps = wx.CheckBox(self, label="through AC-coupling capacitors")
        self.caps.SetValue(True)
        find_btn = wx.Button(self, label="Find chains")
        find_btn.Bind(wx.EVT_BUTTON, self.on_find)
        opts.Add(wx.StaticText(self, label="Series resistors up to (Ω)"), 0,
                 wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        opts.Add(self.ohms, 0, wx.RIGHT, 12)
        opts.Add(self.caps, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        opts.Add(find_btn)
        self.include_pair = wx.CheckBox(self, label='Include differential partner')
        self.include_pair.SetValue(True)
        opts.Add(self.include_pair, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        endpoint_button = wx.Button(self, label='Detect path from 2 selected PCB items')
        endpoint_button.Enable(detect_selected is not None)
        endpoint_button.Bind(wx.EVT_BUTTON, lambda event: self.detect_endpoints())
        pick_button = wx.Button(self, label='Pick first, then second endpoint in PCB...')
        pick_button.Enable(pick_endpoint is not None)
        pick_button.Bind(wx.EVT_BUTTON, self.pick_path)
        self.path_preview = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY,
                                       size=(-1, 75))
        self.path_preview.ChangeValue('Select two pads, vias, tracks or components, then click '
                                     'Use KiCad selection or Detect path. For component searches, '
                                     'pick source and destination footprints separately.')

        # ---- chain list
        self.list = dv.DataViewListCtrl(self, style=dv.DV_ROW_LINES | dv.DV_MULTIPLE)
        self.list.AppendToggleColumn(COLS[0], width=45, mode=dv.DATAVIEW_CELL_ACTIVATABLE)
        self.list.AppendTextColumn(COLS[1], width=170)
        self.list.AppendTextColumn(COLS[2], width=130, mode=dv.DATAVIEW_CELL_EDITABLE)
        self.list.AppendTextColumn(COLS[3], width=110)
        self.list.AppendTextColumn(COLS[4], width=380)
        self.list.AppendTextColumn(COLS[5], width=110)
        self.list.Bind(dv.EVT_DATAVIEW_ITEM_VALUE_CHANGED, self.on_cell)

        # ---- group limits
        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(0, 4)
        for i, name in enumerate(("Group", "Skew ps", "Pair skew ps", "Stub max ps")):
            self.grid.SetColLabelValue(i, name)
        self.grid.SetRowLabelSize(0)
        self.grid.SetColSize(0, 200)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Untick all", lambda e: self.set_keep(False)),
                               ("Tick all", lambda e: self.set_keep(True)),
                               ("Remove unticked", self.on_remove)):
            b = wx.Button(self, label=label)
            b.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(b, 0, wx.RIGHT, 4)
        buttons.AddStretchSpacer()
        buttons.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL))
        self.FindWindowById(wx.ID_OK).SetLabel("Apply && save")
        self.status = wx.StaticText(self, label="")

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(top, 0, wx.ALL, 8)
        box.Add(opts, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        box.Add(endpoint_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        box.Add(pick_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        box.Add(self.path_preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        box.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        box.Add(wx.StaticText(self, label="Group limits (blank = not checked)"), 0, wx.ALL, 8)
        self.grid.SetMinSize((-1, 190))  # fixed height; scrolls, leaving the chain list room
        self.grid.SetMaxSize((-1, 190))
        box.Add(self.grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        box.Add(self.status, 0, wx.ALL, 8)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(box)
        self.refresh()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_BUTTON, self.on_cancel, id=wx.ID_CANCEL)

    def on_close(self, event):
        if self.working:
            event.Veto()
        else:
            event.Skip()

    def on_cancel(self, event):
        if not self.working:
            self.EndModal(wx.ID_CANCEL)

    def task(self, fn, done):
        if self.working:
            return
        self.working = True
        self.Enable(False)
        self.status.SetLabel('Reading PCB selection and detecting path...')

        def finish(value, error):
            if self.closed:
                return
            self.working = False
            self.Enable(True)
            if error:
                self.status.SetLabel(f'Detection failed: {error}')
                self.path_preview.ChangeValue(str(error))
            else:
                try:
                    done(value)
                except Exception as exc:
                    self.status.SetLabel(f'Detection failed: {exc}')

        def work():
            try:
                value, error = fn(), None
            except Exception as exc:
                value, error = None, exc
            wx.CallAfter(finish, value, error)
        self.worker.submit(work)

    def use_selection(self, field):
        # The old callback returns component references only. Pads/vias have no refs;
        # do not silently replace the text field with an empty string in that case.
        options = self.endpoint_options()
        def work():
            if self.selection_items:
                items = self.selection_items()
                if len(items) == 2 and self.detect_selected:
                    return None, self.detect_selected(**options)
                refs = [item['ref'] for item in items if 'ref' in item]
            else:
                refs = self.selection()
            if refs and (len(set(refs)) != 2 or not self.detect_selected):
                return refs, None
            if self.detect_selected:
                return None, self.detect_selected(**options)
            raise ValueError('No footprints selected. Select source/destination footprints '
                             'or reopen TraceForge for pad/via endpoint detection.')
        def done(result):
            refs, path = result
            if refs:
                field.SetValue(', '.join(dict.fromkeys(refs)))
                self.status.SetLabel('Component references filled. Set the other endpoint, '
                                     'then Find chains. Select two pads/vias for routed detection.')
            else:
                self.accept_endpoints(path)
        self.task(work, done)

    def endpoint_options(self):
        return dict(max_ohms=self.ohms.GetValue(), capacitors=self.caps.GetValue(),
                    include_pair=self.include_pair.GetValue())

    def pick_path(self, event):
        if not self.pick_endpoint:
            return
        options = self.endpoint_options()
        def work():
            wx.CallAfter(self.status.SetLabel, 'Click FIRST endpoint in PCB Editor. Esc cancels.')
            first = self.pick_endpoint('TraceForge: click FIRST path endpoint. Esc cancels.')
            wx.CallAfter(self.status.SetLabel,
                         f"First: {first['label']}. Click SECOND endpoint in PCB Editor.")
            second = self.pick_endpoint('TraceForge: click SECOND path endpoint. Esc cancels.')
            return self.detect_selected(endpoints=[first['id'], second['id']], **options)
        self.task(work, self.accept_endpoints)

    def detect_endpoints(self):
        if self.detect_selected:
            options = self.endpoint_options()
            self.task(lambda: self.detect_selected(**options), self.accept_endpoints)

    def accept_endpoints(self, result):
        if 'choices' in result:
            choices = result['choices']
            with wx.SingleChoiceDialog(self, 'Several signal paths connect these components. '
                                       'Choose an endpoint pair (first 128 shown).',
                                       'Choose signal path',
                                       [c['label'] for c in choices]) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    self.status.SetLabel('Path choice cancelled; no chains added.')
                    return
                endpoints = choices[dialog.GetSelection()]['endpoints']
            options = self.endpoint_options()
            self.task(lambda: self.detect_selected(endpoints=endpoints, **options),
                      self.accept_endpoints)
            return
        paths = [p for p in (result['primary'], result['partner']) if p]
        details = []
        for path in paths:
            details.append(' -> '.join(e['label'] for e in path['endpoints']) + ': ' +
                           ' -> '.join(path['nets']))
            details.append('Series: ' + (', '.join(f"{c['reference']} ({c['value']})"
                                                  for c in path['components']) or 'none'))
        if result['pair_note']:
            details.append(result['pair_note'])
        details.append('Preview: routed endpoint path. Saved chain: whole nets and branches.')
        self.path_preview.ChangeValue('\n'.join(details))
        if result['pair_note'] and not result['partner']:
            self.status.SetLabel('Path highlighted. Resolve partner or disable Include '
                                 'differential partner and detect again before adding.')
            return
        found = [FoundChain('', tuple(p['nets']), tuple(p['series']),
                            p['endpoints'][0]['label'], p['endpoints'][1]['label']) for p in paths]
        name_and_group(found)
        existing = [next((c for c in self.chains if set(p['nets']) <= set(c.nets) and
                         set(p['series']) <= set(c.series)), None) for p in paths]
        groups = {c.group for c in existing if c}
        if len(groups) == 1:
            for chain in found:
                chain.group = next(iter(groups))
        names = {c.name for c in self.chains}
        members, added = [], 0
        for candidate, previous in zip(found, existing):
            if previous:
                members.append(previous)
                continue
            base, suffix = candidate.name, 2
            while candidate.name in names:
                candidate.name, suffix = f'{base}_{suffix}', suffix + 1
            names.add(candidate.name)
            candidate.pair = None
            self.limits.setdefault(candidate.group, (None, None, None))
            self.chains.append(candidate)
            members.append(candidate)
            added += 1
        if len(members) == 2:
            a, b = members
            if a.group == b.group and a.pair in (None, b.name) and b.pair in (None, a.name):
                a.pair, b.pair = b.name, a.name
        self.refresh()
        self.list.UnselectAll()
        for member in members:
            row = self.chains.index(member)
            self.list.SelectRow(row)
        if members:
            self.list.EnsureVisible(self.list.RowToItem(self.chains.index(members[0])))
        labels = ', '.join(f'{c.group}/{c.name}' for c in members)
        self.status.SetLabel(f'Path highlighted and zoomed. {added} new chain(s) staged; '
                             f'{len(members) - added} already in list: {labels}. '
                             'Apply & save to keep changes.')

    # ------------------------------------------------------------------ list <-> model
    def refresh(self) -> None:
        self.list.DeleteAllItems()
        for c in self.chains:
            path = " → ".join(_short(n) for n in c.nets)
            self.list.AppendItem([c.keep, c.name, c.group, c.pair or "", path,
                                  ", ".join(c.series)])
        self.refresh_groups()
        kept = sum(c.keep for c in self.chains)
        self.status.SetLabel(f"{len(self.chains)} chains, {kept} kept, "
                             f"{len({c.group for c in self.chains if c.keep})} groups")

    def refresh_groups(self) -> None:
        self._read_grid()
        groups = sorted({c.group for c in self.chains if c.keep})
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        self.grid.AppendRows(len(groups))
        for r, g in enumerate(groups):
            if g not in self.limits:
                members = [c for c in self.chains if c.group == g and c.keep]
                skew, pair, stub = _group_for(members[0].name)[1] if members[0].name else (
                    DEFAULT_LIMITS)
                has_pair = any(c.pair for c in members)
                has_stub = any(len(c.nets) > 1 for c in members)
                self.limits[g] = (skew, pair if has_pair else None,
                                  (stub or DEFAULT_LIMITS[2])
                                  if has_stub and any((skew, pair, stub)) else None)
            self.grid.SetCellValue(r, 0, g)
            self.grid.SetReadOnly(r, 0)
            for col, v in enumerate(self.limits[g], 1):
                self.grid.SetCellValue(r, col, "" if v is None else f"{v:g}")

    def _read_grid(self) -> None:
        for r in range(self.grid.GetNumberRows()):
            vals = []
            for col in (1, 2, 3):
                text = self.grid.GetCellValue(r, col).strip()
                try:
                    vals.append(float(text) if text else None)
                except ValueError:
                    vals.append(None)
            self.limits[self.grid.GetCellValue(r, 0)] = tuple(vals)

    def on_cell(self, event: dv.DataViewEvent) -> None:
        row = self.list.ItemToRow(event.GetItem())
        if row < 0:
            return
        c = self.chains[row]
        c.keep = bool(self.list.GetToggleValue(row, 0))
        c.group = self.list.GetTextValue(row, 2).strip() or c.group
        self.refresh_groups()

    def set_keep(self, value: bool) -> None:
        rows = [self.list.ItemToRow(i) for i in self.list.GetSelections()]
        rows = rows or range(len(self.chains))
        for r in rows:
            self.chains[r].keep = value
        self.refresh()

    def on_remove(self, _event) -> None:
        self.chains = [c for c in self.chains if c.keep]
        self.refresh()

    # ------------------------------------------------------------------ find
    def on_find(self, _event) -> None:
        split = lambda s: [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]  # noqa
        src, dst = split(self.src.GetValue()), split(self.dst.GetValue())
        if not src and not dst and self.detect_selected:
            self.detect_endpoints()
            return
        if not src or not dst:
            self.status.SetLabel("enter source and destination references (e.g. U6 → U12, U16)")
            return
        try:
            found = self.find(src, dst, self.ohms.GetValue(), self.caps.GetValue())
        except Exception as exc:
            self.status.SetLabel(f"find failed: {exc}")
            return
        known = {frozenset(c.nets) for c in self.chains}
        new = [c for c in found if frozenset(c.nets) not in known]
        self.chains += new
        self.chains.sort(key=lambda c: (c.group, c.name))
        self.refresh()
        unticked = sum(not c.keep for c in new)
        self.status.SetLabel(f"found {len(found)} chains, {len(new)} new "
                             f"({unticked} unticked: no timing netclass)")

    # ------------------------------------------------------------------ result
    def result(self) -> Config:
        self._read_grid()
        groups: dict[str, GroupSuggestion] = {}
        for c in self.chains:
            if c.keep:
                lim = self.limits.get(c.group, DEFAULT_LIMITS)
                groups.setdefault(c.group, GroupSuggestion(c.group, *lim)).chains.append(c)
        cfg = merge_into(None, groups.values(), self.die)
        # keep pair links only inside the same group
        cfg.groups = [GroupDef(g.name, tuple(ch if ch.pair in {x.name for x in g.chains}
                                             else type(ch)(ch.group, ch.name, ch.nets, ch.series)
                                             for ch in g.chains),
                               g.skew_ps, g.pair_skew_ps, g.stub_max_ps) for g in cfg.groups]
        return cfg


def edit_chains(parent: Optional[wx.Window], config: Optional[Config], find, selection,
                save: Callable[[Config], str], detect_selected=None, selection_items=None,
                pick_endpoint=None) -> str:
    dlg = ChainEditor(parent, config, find, selection, detect_selected=detect_selected,
                      selection_items=selection_items, pick_endpoint=pick_endpoint)
    try:
        if dlg.ShowModal() == wx.ID_OK:
            return save(dlg.result())
        return "chain editor closed without changes"
    finally:
        dlg.closed = True
        dlg.worker.shutdown(wait=False, cancel_futures=True)
        dlg.Destroy()
