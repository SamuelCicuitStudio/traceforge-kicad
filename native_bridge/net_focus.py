"""Targeted native highlight actions using KiCad's configured shortcuts."""
import os
import shutil
from pathlib import Path

import pcbnew
import wx


def hotkeys_path():
    manager = pcbnew.GetSettingsManager()
    config = (Path(manager.GetUserSettingsPath()) if manager else
              Path(os.environ.get('APPDATA', Path.home())) / 'kicad/10.0')
    return config / 'user.hotkeys'


def prepare_shortcut():
    """Assign the native focus action once for PCM installs; return if restart is needed."""
    path = hotkeys_path()
    lines = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    action = 'pcbnew.EditorControl.highlightNetSelection'
    shortcut_value = 'Ctrl+Alt+Shift+F12'
    assigned = next((fields[1] for line in lines
                     if (fields := line.split('\t'))[0] == action and len(fields) > 1), '')
    if assigned:
        return False
    if any((fields := line.split('\t'))[0] != action and len(fields) > 1 and
           fields[1] == shortcut_value for line in lines):
        raise ValueError('Ctrl+Alt+Shift+F12 is already assigned in KiCad. Assign '
                         'Highlight Net (selected nets) in Preferences > Hotkeys, '
                         'then restart PCB Editor.')
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.traceforge.bak'))
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [line for line in lines if line.split('\t')[0] != action]
    lines.append(f'{action}\t{shortcut_value}\t')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return True


def shortcut(action):
    name = {'highlightNet': 'highlightNetSelection', 'clearHighlight': 'clearHighlight'}[action]
    value = '~' if name == 'clearHighlight' else ''
    path = hotkeys_path()
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            fields = line.split('\t')
            if fields[0] == 'pcbnew.EditorControl.' + name:
                value = fields[1] if len(fields) > 1 else ''
                break
    if not value:
        label = ('Highlight Net (selected nets)' if name == 'highlightNetSelection'
                 else 'Clear Net Highlighting')
        raise ValueError(f'KiCad shortcut is unassigned: {label}. '
                         'Assign it in Preferences > Hotkeys and restart PCB Editor. '
                         f'File: {path}')
    return value


def run(action):
    frame = next((w for w in wx.GetTopLevelWindows() if isinstance(w, wx.Frame) and
                  w.GetTitle().endswith('PCB Editor')), None)
    if frame is None:
        return False
    candidates = []
    def visit(window, depth):
        size = window.GetClientSize()
        if (depth and window.IsShownOnScreen() and not isinstance(window, wx.Control) and
                size.width > frame.GetClientSize().width * .4 and size.height > 200):
            candidates.append((size.width * size.height, depth, window))
        for child in window.GetChildren():
            visit(child, depth + 1)
    visit(frame, 0)
    if not candidates:
        raise ValueError('KiCad drawing canvas was not found for native net focus.')
    parts = shortcut(action).split('+')
    name = parts[-1]
    code = ord(name.upper()) if len(name) == 1 and name.isalpha() else (
        ord(name) if len(name) == 1 else getattr(wx, 'WXK_' + name.upper(), 0))
    if not code:
        raise ValueError('Unsupported native net-focus shortcut. '
                         'Assign a character or function key.')
    for _, _, canvas in sorted(candidates, key=lambda row: row[:2], reverse=True):
        event = wx.KeyEvent(wx.EVT_CHAR.typeId)
        event.SetKeyCode(code)
        event.SetUnicodeKey(code if len(name) == 1 else wx.WXK_NONE)
        event.SetControlDown('Ctrl' in parts)
        event.SetAltDown('Alt' in parts)
        event.SetShiftDown('Shift' in parts)
        event.SetEventObject(canvas)
        if canvas.GetEventHandler().ProcessEvent(event):
            return True
    return False
