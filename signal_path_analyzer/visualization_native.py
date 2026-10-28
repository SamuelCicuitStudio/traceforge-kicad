"""Live KiCad Appearance controls, called on PCB Editor's main thread."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pcbnew
import wx
import wx.grid


def _frame():
    frame = next((window for window in wx.GetTopLevelWindows()
                  if isinstance(window, wx.Frame) and
                  window.GetTitle().endswith('PCB Editor')), None)
    if frame is None:
        raise RuntimeError('PCB Editor window is unavailable')
    return frame


def _children(window):
    for child in window.GetChildren():
        yield child
        yield from _children(child)


def _net_grid(frame, board):
    names = {net.GetNetname() for net in board.GetNetsByNetcode().values()}
    for grid in _children(frame):
        if not isinstance(grid, wx.grid.Grid) or grid.GetNumberCols() != 3:
            continue
        rows = {grid.GetCellValue(row, 2): row
                for row in range(grid.GetNumberRows())}
        if names.intersection(rows):
            return grid, rows
    raise RuntimeError('KiCad Appearance > Nets panel is unavailable')


def _net_settings(board):
    return board.GetDesignSettings().m_NetSettings


def _show_colors_on_copper(frame):
    for radio in _children(frame):
        if not isinstance(radio, wx.RadioButton) or radio.GetLabel() != 'All':
            continue
        siblings = {child.GetLabel() for child in radio.GetParent().GetChildren()
                    if isinstance(child, wx.RadioButton)}
        if not {'All', 'Ratsnest', 'None'}.issubset(siblings):
            continue
        if not radio.GetValue():
            radio.SetValue(True)
            event = wx.CommandEvent(wx.EVT_RADIOBUTTON.typeId, radio.GetId())
            event.SetEventObject(radio)
            radio.GetEventHandler().ProcessEvent(event)
        return
    raise RuntimeError('KiCad Net colors > All control was not found')


def _show_ratsnest_on_all_layers(frame):
    for radio in _children(frame):
        if not isinstance(radio, wx.RadioButton) or radio.GetLabel() != 'All':
            continue
        siblings = {child.GetLabel() for child in radio.GetParent().GetChildren()
                    if isinstance(child, wx.RadioButton)}
        if not {'All', 'Visible layers', 'None'}.issubset(siblings):
            continue
        if not radio.GetValue():
            radio.SetValue(True)
            event = wx.CommandEvent(wx.EVT_RADIOBUTTON.typeId, radio.GetId())
            event.SetEventObject(radio)
            radio.GetEventHandler().ProcessEvent(event)
        return
    raise RuntimeError('KiCad Ratsnest display > All control was not found')


def _save_project(board):
    project = Path(board.GetFileName()).with_suffix('.kicad_pro')
    if project.is_file() and not pcbnew.GetSettingsManager().SaveProject(str(project)):
        raise RuntimeError('KiCad could not save net colors to the project')


def _selected_component_nets():
    footprints = {}
    for item in pcbnew.GetCurrentSelection():
        if isinstance(item, pcbnew.FOOTPRINT):
            footprints[item.m_Uuid.AsString()] = item
        elif isinstance(item, pcbnew.PAD) and hasattr(item, 'GetParentFootprint'):
            fp = item.GetParentFootprint()
            if fp is not None:
                footprints[fp.m_Uuid.AsString()] = fp
    if not footprints:
        raise ValueError('Select a footprint or one of its pads in PCB Editor first')
    return {fp.GetReference(): sorted({pad.GetNetname() for pad in fp.Pads()
                                       if pad.GetNetCode() > 0})
            for fp in footprints.values()}


def _find_teardrop_menu(menu):
    for item in menu.GetMenuItems():
        label = item.GetItemLabelText().lower().replace('…', '').replace('.', '').strip()
        if 'teardrop' in label and ('edit' in label or 'set' in label):
            return menu, item.GetId()
        child = item.GetSubMenu()
        if child is not None:
            found = _find_teardrop_menu(child)
            if found is not None:
                return found
    return None


def _post_editor_menu(frame, command):
    """Deliver a native menu command to KiCad's frame HWND.

    KiCad's PCB_ACTIONS menu commands are handled by its C++ window procedure.
    A synthetic wx.CommandEvent is accepted by wx but does not reach that handler.
    """
    if os.name != 'nt':
        raise RuntimeError('Direct KiCad menu commands are supported on Windows only.')
    post = ctypes.windll.user32.PostMessageW
    post.argtypes = (ctypes.c_void_p, ctypes.c_uint,
                     ctypes.c_size_t, ctypes.c_ssize_t)
    post.restype = ctypes.c_bool
    if not post(frame.GetHandle(), 0x0111, command, 0):  # WM_COMMAND
        raise RuntimeError('Windows could not send the teardrop command to PCB Editor.')


def dispatch(board, operation, payload):
    frame = _frame()
    if operation == 'visual_teardrops':
        menu_bar = frame.GetMenuBar()
        if menu_bar is None:
            raise RuntimeError('KiCad menu bar is unavailable')
        target = next((found for index in range(menu_bar.GetMenuCount())
                       if (found := _find_teardrop_menu(menu_bar.GetMenu(index))) is not None),
                      None)
        if target is None:
            raise RuntimeError('KiCad Edit Teardrops command was not found')
        _menu, command = target
        _post_editor_menu(frame, command)
        return {'opened': True}

    grid, rows = _net_grid(frame, board)
    if operation == 'visual_state':
        nets = {}
        for net in board.GetNetsByNetcode().values():
            name = net.GetNetname()
            if name in rows and name:
                row = rows[name]
                nets[name] = {'netclass': net.GetNetClassName(),
                              'color': grid.GetCellValue(row, 0),
                              'visible': grid.GetCellValue(row, 1) != '0'}
        return {'nets': nets}

    if operation == 'visual_colors':
        updates = payload.get('updates', {})
        if not isinstance(updates, dict) or not updates:
            raise ValueError('Choose one or more net colors')
        missing = sorted(set(updates) - set(rows))
        if missing:
            raise ValueError('Nets no longer on this board: ' + ', '.join(missing[:8]))
        for color in updates.values():
            if color is not None and (not isinstance(color, str) or
                                      not color.startswith('#') or len(color) != 7 or
                                      any(ch not in '0123456789abcdefABCDEF' for ch in color[1:])):
                raise ValueError('Color must be #RRGGBB')
        settings = _net_settings(board)
        for name, color in updates.items():
            value = color or 'rgba(0,0,0,0)'
            grid.SetCellValue(rows[name], 0, value)
            assigned = pcbnew.COLOR4D(value) if color else pcbnew.COLOR4D.UNSPECIFIED
            settings.SetNetColorAssignment(name, assigned)
        if any(color for color in updates.values()):
            _show_colors_on_copper(frame)
        grid.ForceRefresh()
        _save_project(board)
        return {'changed': len(updates)}

    if operation == 'visual_ratsnest':
        mode = payload.get('mode')
        components = {}
        if mode == 'all':
            shown = set(rows)
            candidates = rows
        elif mode == 'none':
            shown = set()
            candidates = rows
        elif mode == 'selection':
            components = _selected_component_nets()
            added = set().union(*(set(nets) for nets in components.values())) & set(rows)
            if not added:
                raise ValueError('Selected component has no connected nets')
            if payload.get('replace', False):
                shown = added
                candidates = rows
            else:
                shown = {name for name, row in rows.items()
                         if grid.GetCellValue(row, 1) != '0'} | added
                candidates = added
        elif mode == 'remove':
            hidden = set(payload.get('hide', [])) & set(rows)
            shown = {name for name, row in rows.items()
                     if grid.GetCellValue(row, 1) != '0'} - hidden
            candidates = hidden
        else:
            raise ValueError('Unknown ratsnest visibility mode')
        changed = [(rows[name], '1' if name in shown else '0') for name in candidates
                   if grid.GetCellValue(rows[name], 1) != ('1' if name in shown else '0')]
        if changed:
            grid.BeginBatch()
            try:
                for row, wanted in changed:
                    grid.SetCellValue(row, 1, wanted)
            finally:
                grid.EndBatch()
        if shown:
            _show_ratsnest_on_all_layers(frame)
        grid.ForceRefresh()
        return {'shown': len(shown), 'total': len(rows), 'components': components,
                'changed': len(changed)}

    raise ValueError(f'Unsupported visualization operation: {operation}')
