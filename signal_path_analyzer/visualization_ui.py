"""Net colors, ratsnest focus and KiCad teardrop access."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import wx


def matches(patterns, nets):
    result = set()
    for raw in patterns.split(','):
        pattern = raw.strip()
        if not pattern:
            continue
        if pattern.lower().startswith('class:'):
            mask = pattern[6:].strip()
            result.update(name for name, value in nets.items()
                          if fnmatch.fnmatchcase(value['netclass'], mask))
        else:
            result.update(name for name in nets if fnmatch.fnmatchcase(name, pattern))
    return result


class VisualizationPanel(wx.Panel):
    def __init__(self, parent, host, native, board_file):
        super().__init__(parent)
        self.host, self.native = host, native
        self.sidecar = Path(board_file or 'TraceForge.kicad_pcb').with_suffix(
            '.traceforge-visual.json')
        self.groups, self.individuals, self.nets = [], {}, {}
        self.focus_active = False
        self.focused_components = {}
        try:
            data = json.loads(self.sidecar.read_text(encoding='utf-8'))
            self.groups = data.get('groups', [])
            self.individuals = data.get('individuals', {})
        except (OSError, ValueError, TypeError):
            pass

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label='Net colors are shown on pads, tracks, vias and zones '
                               'when KiCad Appearance > Nets > Net colors is set to All.'),
                  0, wx.ALL, 8)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        for title, handler in (('Refresh nets', self.on_refresh),
                               ('Reset all net colors to defaults', self.on_reset_colors),
                               ('Edit teardrops in KiCad', self.on_teardrops)):
            button = wx.Button(self, label=title)
            button.Bind(wx.EVT_BUTTON, handler)
            bar.Add(button, 0, wx.RIGHT, 5)
        outer.Add(bar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label='Ratsnest visibility'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        outer.Add(wx.StaticText(self, label='Select a footprint or pad in PCB Editor, then click '
                               'Add PCB selection. Each click keeps the previous components.'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        ratsnest_bar = wx.BoxSizer(wx.HORIZONTAL)
        for title, mode in (('Show all', 'all'), ('Hide all', 'none'),
                            ('Add PCB selection', 'selection')):
            button = wx.Button(self, label=title)
            button.Bind(wx.EVT_BUTTON, lambda event, mode=mode: self.ratsnest(mode))
            ratsnest_bar.Add(button, 0, wx.RIGHT, 8)
        outer.Add(ratsnest_bar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        outer.Add(wx.StaticText(self, label='Focused components (select one to remove):'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        focus_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.focus_list = wx.ListBox(self, size=(340, 64))
        focus_bar.Add(self.focus_list, 0, wx.RIGHT, 8)
        remove_focus = wx.Button(self, label='Remove selected component')
        remove_focus.Bind(wx.EVT_BUTTON, self.on_focus_remove)
        focus_bar.Add(remove_focus, 0, wx.ALIGN_TOP)
        outer.Add(focus_bar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label='Color groups: comma-separated net names, globs, '
                               'or class:NETCLASS. Every member gets the same color.'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        form = wx.BoxSizer(wx.HORIZONTAL)
        self.group_name = wx.TextCtrl(self, size=(150, -1))
        self.patterns = wx.TextCtrl(self, size=(280, -1))
        self.group_color = wx.TextCtrl(self, value='#44AAFF', size=(90, -1))
        for label, field in (('Group', self.group_name), ('Members', self.patterns),
                             ('Color', self.group_color)):
            form.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            form.Add(field, 0, wx.RIGHT, 9)
        choose = wx.Button(self, label='Choose color')
        choose.Bind(wx.EVT_BUTTON, lambda e: self.choose_color(self.group_color))
        form.Add(choose, 0, wx.RIGHT, 5)
        apply = wx.Button(self, label='Save / apply group')
        apply.Bind(wx.EVT_BUTTON, self.on_group_apply)
        form.Add(apply)
        outer.Add(form, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.group_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                                     size=(-1, 145))
        for index, (label, width) in enumerate((('Group', 160), ('Members', 370),
                                                ('Color', 95), ('Matched nets', 110))):
            self.group_list.InsertColumn(index, label, width=width)
        self.group_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_group_selected)
        outer.Add(self.group_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        remove = wx.Button(self, label='Remove selected group and its colors')
        remove.Bind(wx.EVT_BUTTON, self.on_group_remove)
        outer.Add(remove, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label='Individual net colors (nets in a color group '
                               'cannot also have an individual assignment):'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        single = wx.BoxSizer(wx.HORIZONTAL)
        self.net = wx.ComboBox(self, style=wx.CB_DROPDOWN, size=(300, -1))
        self.net.Bind(wx.EVT_COMBOBOX, self.on_net_selected)
        self.net_color = wx.TextCtrl(self, value='#FFB347', size=(90, -1))
        single.Add(self.net, 0, wx.RIGHT, 8)
        single.Add(self.net_color, 0, wx.RIGHT, 6)
        picker = wx.Button(self, label='Choose color')
        picker.Bind(wx.EVT_BUTTON, lambda e: self.choose_color(self.net_color))
        single.Add(picker, 0, wx.RIGHT, 5)
        for label, clear in (('Apply net color', False), ('Clear net color', True)):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, lambda event, clear=clear: self.on_net_apply(clear))
            single.Add(button, 0, wx.RIGHT, 5)
        outer.Add(single, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status = wx.StaticText(self, label='Click Refresh nets to read the open PCB.')
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)
        self.fill_groups()

    def message(self, text, state='pending'):
        self.status.SetLabel(text)
        self.status.SetForegroundColour(self.host.colors.get(state, self.host.colors['pending']))
        self.Layout()

    def invalidate(self):
        pass

    def _call(self, operation, done, **payload):
        self.host.submit_stitching(lambda: self.native(operation, **payload), done, self)

    def _save(self):
        self.sidecar.write_text(json.dumps({'version': 1, 'groups': self.groups,
                                            'individuals': self.individuals}, indent=2) + '\n',
                                encoding='utf-8')

    def fill_groups(self):
        self.group_list.DeleteAllItems()
        for group in self.groups:
            count = len(matches(group['patterns'], self.nets)) if self.nets else 0
            row = self.group_list.InsertItem(self.group_list.GetItemCount(), group['name'])
            for col, value in enumerate((group['patterns'], group['color'], str(count)), 1):
                self.group_list.SetItem(row, col, value)

    def on_refresh(self, event=None):
        def done(result):
            self.nets = result['nets']
            current = self.net.GetValue()
            self.net.SetItems(sorted(self.nets))
            self.net.SetValue(current)
            self.fill_groups()
            self.message(f'{len(self.nets)} nets read from PCB Editor.', 'ok')
        self._call('visual_state', done)

    def choose_color(self, field):
        try:
            current = wx.Colour(field.GetValue())
        except Exception:
            current = wx.Colour('#44AAFF')
        data = wx.ColourData()
        data.SetColour(current)
        with wx.ColourDialog(self, data) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                color = dialog.GetColourData().GetColour()
                field.SetValue(f'#{color.Red():02X}{color.Green():02X}{color.Blue():02X}')

    @staticmethod
    def valid_color(text):
        color = text.strip()
        if len(color) != 7 or color[0] != '#' or any(
                char not in '0123456789abcdefABCDEF' for char in color[1:]):
            raise ValueError('Enter a color as #RRGGBB')
        return color.upper()

    def on_group_selected(self, event):
        group = self.groups[event.GetIndex()]
        self.group_name.SetValue(group['name'])
        self.patterns.SetValue(group['patterns'])
        self.group_color.SetValue(group['color'])

    def on_group_apply(self, event):
        try:
            name = self.group_name.GetValue().strip()
            patterns = self.patterns.GetValue().strip()
            color = self.valid_color(self.group_color.GetValue())
            if not name or not patterns:
                raise ValueError('Enter a group name and members')
            if not self.nets:
                raise ValueError('Click Refresh nets first')
            members = matches(patterns, self.nets)
            if not members:
                raise ValueError('No PCB nets match these members')
            other = set().union(*(matches(g['patterns'], self.nets) for g in self.groups
                                  if g['name'] != name)) if self.groups else set()
            conflict = members & (other | set(self.individuals))
            if conflict:
                raise ValueError('Nets already assigned elsewhere: ' +
                                 ', '.join(sorted(conflict)[:6]))
            old = next((g for g in self.groups if g['name'] == name), None)
            previous = matches(old['patterns'], self.nets) if old else set()
            updates = {net: None for net in previous - members}
            updates.update({net: color for net in members})
        except ValueError as exc:
            self.message(str(exc), 'warning')
            return
        def done(result):
            for net, assigned in updates.items():
                self.nets[net]['color'] = assigned or 'rgba(0, 0, 0, 0.000)'
            self.groups = [g for g in self.groups if g['name'] != name]
            self.groups.append({'name': name, 'patterns': patterns, 'color': color})
            self._save()
            self.fill_groups()
            self.message(f'{name}: colored {len(members)} nets live in KiCad.', 'ok')
        self._call('visual_colors', done, updates=updates)

    def on_group_remove(self, event):
        if not self.nets:
            self.message('Click Refresh nets before removing a group.', 'warning')
            return
        selected = self.group_list.GetFirstSelected()
        if selected < 0:
            self.message('Select a group to remove.', 'warning')
            return
        group = self.groups[selected]
        members = matches(group['patterns'], self.nets)
        def done(result):
            for net in members:
                self.nets[net]['color'] = 'rgba(0, 0, 0, 0.000)'
            self.groups.pop(selected)
            self._save()
            self.fill_groups()
            self.message(f'Removed {group["name"]}.', 'ok')
        if members:
            self._call('visual_colors', done, updates={net: None for net in members})
        else:
            done({})

    def on_net_selected(self, event):
        color = self.nets.get(self.net.GetValue(), {}).get('color', '')
        if color.startswith('#') and len(color) == 7:
            self.net_color.SetValue(color.upper())
        elif color.startswith('rgb('):
            try:
                channels = [int(part.strip()) for part in color[4:-1].split(',')]
                self.net_color.SetValue('#{:02X}{:02X}{:02X}'.format(*channels))
            except (ValueError, IndexError):
                pass

    def on_net_apply(self, clear):
        name = self.net.GetValue().strip()
        if name not in self.nets:
            self.message('Choose an exact net name from the PCB.', 'warning')
            return
        if any(name in matches(group['patterns'], self.nets) for group in self.groups):
            self.message('This net belongs to a color group. Edit that group instead.', 'warning')
            return
        try:
            color = None if clear else self.valid_color(self.net_color.GetValue())
        except ValueError as exc:
            self.message(str(exc), 'warning')
            return
        def done(result):
            self.nets[name]['color'] = color or 'rgba(0, 0, 0, 0.000)'
            if color:
                self.individuals[name] = color
            else:
                self.individuals.pop(name, None)
            self._save()
            self.message(f'{name}: color {color or "cleared"} in KiCad.', 'ok')
        self._call('visual_colors', done, updates={name: color})

    def on_reset_colors(self, event=None):
        if not self.nets:
            self.message('Click Refresh nets before resetting colors.', 'warning')
            return
        def done(result):
            for details in self.nets.values():
                details['color'] = 'rgba(0, 0, 0, 0.000)'
            self.groups.clear()
            self.individuals.clear()
            self._save()
            self.group_name.Clear()
            self.patterns.Clear()
            self.fill_groups()
            self.message(f'Reset colors for {result["changed"]} nets to KiCad defaults.', 'ok')
        self._call('visual_colors', done, updates={name: None for name in self.nets})

    def fill_focused(self):
        self.focus_refs = sorted(self.focused_components)
        self.focus_list.SetItems([f'{ref} ({len(self.focused_components[ref])} nets)'
                                  for ref in self.focus_refs])

    def ratsnest(self, mode):
        replace = mode == 'selection' and not self.focus_active
        def done(result):
            if mode == 'selection':
                if replace:
                    self.focused_components.clear()
                self.focused_components.update(
                    {ref: set(nets) for ref, nets in result['components'].items()})
                self.focus_active = True
            else:
                self.focused_components.clear()
                self.focus_active = mode == 'none'
            self.fill_focused()
            refs = ', '.join(result['components'])
            detail = f' Added {refs}.' if refs else ''
            self.message(f'Ratsnest: {result["shown"]} of {result["total"]} nets visible; '
                         f'{result["changed"]} changed.' + detail, 'ok')
        self._call('visual_ratsnest', done, mode=mode, replace=replace)

    def on_focus_remove(self, event=None):
        index = self.focus_list.GetSelection()
        if index == wx.NOT_FOUND:
            self.message('Select a component in the focus list to remove.', 'warning')
            return
        ref = self.focus_refs[index]
        old_nets = set().union(*self.focused_components.values())
        remaining = {name: nets for name, nets in self.focused_components.items()
                     if name != ref}
        new_nets = set().union(*remaining.values()) if remaining else set()
        hidden = old_nets - new_nets
        def done(result):
            self.focused_components.pop(ref, None)
            self.fill_focused()
            self.message(f'Removed {ref}; {len(new_nets)} focused nets remain.', 'ok')
        if hidden:
            self._call('visual_ratsnest', done, mode='remove', hide=sorted(hidden))
        else:
            done({})

    def on_teardrops(self, event):
        self._call('visual_teardrops',
                   lambda result: self.message('KiCad Edit Teardrops opened.', 'ok'))
