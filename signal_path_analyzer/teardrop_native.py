"""Apply TraceForge teardrop settings through KiCad's native editor command.

KiCad 10 does not expose its teardrop generator through pcbnew. The native
dialog owns the generator and undo transaction, so this adapter fills that
dialog and invokes its Apply and Close action on PCB Editor's wx thread.
"""
from __future__ import annotations

import secrets
import time

import pcbnew
import wx

from .visualization_native import _find_teardrop_menu, _frame, _post_editor_menu

_job = None


def _count(board):
    return sum(zone.IsTeardropArea() for zone in board.Zones())


def _children(window):
    for child in window.GetChildren():
        yield child
        yield from _children(child)


def _labeled(dialog, kind, label):
    matches = [child for child in _children(dialog)
               if isinstance(child, kind) and
               child.GetLabel().replace('&', '').strip().casefold() == label.casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'KiCad teardrop control not found: {label}')
    return matches[0]


def _dialog(existing):
    return next((window for window in wx.GetTopLevelWindows()
                 if isinstance(window, wx.Dialog) and window.GetHandle() not in existing and
                 'teardrop' in window.GetTitle().casefold()), None)


def _percent(value, label, maximum=500):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number.') from exc
    if not 0 <= result <= maximum:
        raise ValueError(f'{label} must be between 0 and {maximum}%.')
    return f'{result:g}'


def _millimeters(value, label):
    if value in ('', None):
        return ''  # KiCad's indeterminate value preserves an existing maximum.
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number of millimeters.') from exc
    if not 0 < result <= 100:
        raise ValueError(f'{label} must be greater than 0 and at most 100 mm.')
    return f'{result:g}'


def _validate(settings):
    result = {
        'operation': settings.get('operation'),
        'selected_only': bool(settings.get('selected_only')),
        'vias': bool(settings.get('vias')),
        'pth': bool(settings.get('pth')),
        'smd': bool(settings.get('smd')),
        'tracks': bool(settings.get('tracks')),
        'curved': bool(settings.get('curved')),
        'prefer_zone': bool(settings.get('prefer_zone')),
        'span_two': bool(settings.get('span_two')),
    }
    if result['operation'] not in ('add', 'remove'):
        raise ValueError('Choose Add or Remove.')
    if not any(result[key] for key in ('vias', 'pth', 'smd', 'tracks')):
        raise ValueError('Choose at least one teardrop target.')
    if result['selected_only'] and result['tracks']:
        raise ValueError('Selected-only track-to-track changes are not supported by KiCad 10. '
                         'Uncheck Track to track or choose the whole board.')
    if result['operation'] == 'add' and result['tracks'] and any(
            result[key] for key in ('vias', 'pth', 'smd')):
        raise ValueError('KiCad 10 applies track-to-track teardrops using board defaults. '
                         'Apply them separately from pad/via teardrops.')
    if result['operation'] == 'add':
        result.update(
            track_limit=_percent(settings.get('track_limit'), 'Track width limit', 100),
            length=_percent(settings.get('length'), 'Best length'),
            width=_percent(settings.get('width'), 'Best width'),
            max_length=_millimeters(settings.get('max_length'), 'Maximum length'),
            max_width=_millimeters(settings.get('max_width'), 'Maximum width'))
    return result


def _configure(dialog, settings):
    for label, enabled in (('PTH pads', settings['pth']),
                           ('SMD pads', settings['smd']),
                           ('Vias', settings['vias']),
                           ('Track to track', settings['tracks']),
                           ('Selected items only', settings['selected_only'])):
        _labeled(dialog, wx.CheckBox, label).SetValue(enabled)
    if settings['operation'] == 'remove':
        _labeled(dialog, wx.RadioButton, 'Remove teardrops').SetValue(True)
    else:
        if settings['tracks']:
            _labeled(dialog, wx.RadioButton,
                     'Add teardrops with default values for shape').SetValue(True)
        else:
            _labeled(dialog, wx.RadioButton,
                     'Add teardrops with specified values:').SetValue(True)
            action = _labeled(dialog, wx.StaticBox, 'Action')
            fields = sorted((child for child in _children(action)
                             if isinstance(child, wx.TextCtrl)),
                            key=lambda child: (child.GetScreenPosition().y,
                                               child.GetScreenPosition().x))
            if len(fields) != 5:
                raise RuntimeError('KiCad teardrop dimension controls changed; '
                                   'no edit was applied.')
            for control, name in zip(fields, ('track_limit', 'length', 'max_length',
                                               'width', 'max_width')):
                control.SetValue(settings[name])
            for label, enabled in (('Curved edges', settings['curved']),
                                   ('Prefer zone connection', settings['prefer_zone']),
                                   ('Allow teardrops to span two track segments',
                                    settings['span_two'])):
                _labeled(dialog, wx.CheckBox, label).SetValue(enabled)


def _fail(token, message, dialog=None):
    if _job and _job['token'] == token:
        _job.update(state='error', message=str(message))
    if dialog:
        button = dialog.FindWindowById(wx.ID_CANCEL)
        if button:
            event = wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_CANCEL)
            event.SetEventObject(button)
            wx.PostEvent(button, event)


def _watch(token, dialog_handle):
    if not _job or _job['token'] != token or _job['state'] != 'running':
        return
    still_open = any(window.GetHandle() == dialog_handle
                     for window in wx.GetTopLevelWindows())
    if still_open:
        if time.monotonic() - _job['started'] > 45:
            _fail(token, 'KiCad did not finish the teardrop operation. Check its dialog.')
        else:
            wx.CallLater(200, _watch, token, dialog_handle)
        return
    board = pcbnew.GetBoard()
    if board is None or board.GetFileName() != _job['board']:
        _fail(token, 'The PCB Editor board changed during teardrop generation.')
        return
    try:
        after = _count(board)
    except Exception as exc:
        _fail(token, f'KiCad closed its dialog, but the teardrop count failed: {exc}')
        return
    _job.update(state='complete', before=_job['before'], after=after,
                message=f"KiCad teardrop operation completed. "
                        f"Generated areas: {_job['before']} to {after}.")


def _configure_when_open(token, attempt=0):
    if not _job or _job['token'] != token or _job['state'] != 'running':
        return
    dialog = _dialog(_job['windows'])
    if dialog is None:
        if attempt >= 100:
            _fail(token, 'KiCad Edit Teardrops dialog did not open.')
        else:
            wx.CallLater(100, _configure_when_open, token, attempt + 1)
        return
    try:
        _configure(dialog, _job['settings'])
        button = dialog.FindWindowById(wx.ID_OK)
        if button is None:
            raise RuntimeError('KiCad teardrop Apply and Close button was not found.')
        handle = dialog.GetHandle()
        event = wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_OK)
        event.SetEventObject(button)
        wx.PostEvent(button, event)
        wx.CallLater(200, _watch, token, handle)
    except Exception as exc:
        _fail(token, exc, dialog)


def dispatch(board, operation, payload):
    global _job
    if operation == 'teardrop_status':
        if not _job or payload.get('token') != _job['token']:
            raise ValueError('Teardrop operation is no longer available.')
        return {key: _job[key] for key in ('token', 'state', 'message')}
    if operation != 'teardrop_apply':
        raise ValueError('Unsupported teardrop operation.')
    if _job and _job['state'] == 'running':
        raise ValueError('Another teardrop operation is still running.')
    settings = _validate(payload.get('settings', {}))
    if settings['selected_only'] and not any(
            isinstance(item, (pcbnew.PAD, pcbnew.PCB_VIA))
            for item in pcbnew.GetCurrentSelection()):
        raise ValueError('Select pads or vias in PCB Editor before applying to selected items.')
    frame = _frame()
    menu_bar = frame.GetMenuBar()
    if menu_bar is None:
        raise RuntimeError('KiCad menu bar is unavailable.')
    target = next((found for index in range(menu_bar.GetMenuCount())
                   if (found := _find_teardrop_menu(menu_bar.GetMenu(index))) is not None),
                  None)
    if target is None:
        raise RuntimeError('KiCad Edit Teardrops command was not found.')
    _menu, command = target
    token = secrets.token_hex(12)
    _job = dict(token=token, state='running', message='Applying teardrops in KiCad...',
                settings=settings, board=board.GetFileName(), before=_count(board),
                windows={window.GetHandle() for window in wx.GetTopLevelWindows()},
                started=time.monotonic())
    _post_editor_menu(frame, command)
    wx.CallLater(100, _configure_when_open, token)
    return {'token': token, 'state': 'running'}
