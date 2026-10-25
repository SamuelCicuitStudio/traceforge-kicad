"""One-shot PCB canvas picking. GUI events complete one deferred native request."""
import os

import pcbnew
import wx

_active = None


def finish(value=None, error=None):
    global _active
    job, _active = _active, None
    if job:
        job['timer'].Stop()
        job['reply']({'error': error} if error else {'result': value})


def begin(board, payload, reply):
    global _active
    if _active:
        raise ValueError('A PCB pick is already running. Press Esc in PCB Editor to cancel.')
    mode = payload.get('mode', 'endpoint')
    if mode not in ('endpoint', 'net'):
        raise ValueError('Unknown PCB picking mode.')
    for item in list(pcbnew.GetCurrentSelection()):
        item.ClearSelected()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            pad.ClearSelected()
    pcbnew.Refresh()
    timer = wx.CallLater(90000, finish, error='PCB picking timed out. Click Pick to try again.')
    _active = dict(board=os.path.normcase(os.path.abspath(board.GetFileName())), mode=mode,
                   reply=reply, timer=timer)
    frame = next((w for w in wx.GetTopLevelWindows() if isinstance(w, wx.Frame) and
                  w.GetTitle().endswith('PCB Editor')), None)
    if frame:
        frame.SetStatusText(payload.get('prompt', 'Select one PCB item. Esc cancels.'), 0)
        frame.Raise()


def observe(event):
    if not _active:
        return
    window = event.GetEventObject()
    if not isinstance(window, wx.Window):
        return
    frame = wx.GetTopLevelParent(window)
    if not isinstance(frame, wx.Frame) or not frame.GetTitle().endswith('PCB Editor'):
        return
    if event.GetEventType() == wx.EVT_KEY_DOWN.typeId and event.GetKeyCode() == wx.WXK_ESCAPE:
        finish(error='PCB picking cancelled.')
    elif (event.GetEventType() == wx.EVT_LEFT_UP.typeId and
          not isinstance(window, wx.Control) and window.GetSize().width > 200 and
          window.GetSize().height > 200):
        job = _active
        wx.CallLater(150, capture, job)


def capture(job):
    if _active is not job:
        return
    board = pcbnew.GetBoard()
    if (board is None or os.path.normcase(os.path.abspath(board.GetFileName())) != job['board']):
        finish(error='The open board changed while picking. Start again.')
        return
    items = list(pcbnew.GetCurrentSelection())
    if len(items) != 1:
        return  # Empty or ambiguous click: keep waiting for one actual selected item.
    item = items[0]
    if not isinstance(item, (pcbnew.PAD, pcbnew.PCB_TRACK, pcbnew.FOOTPRINT)):
        return
    net = item.GetNetname().replace('{slash}', '/') if hasattr(item, 'GetNetname') else ''
    if job['mode'] == 'net' and not net:
        return
    label = item.GetReference() if isinstance(item, pcbnew.FOOTPRINT) else net
    finish(dict(id=item.m_Uuid.AsString(), net=net, label=label))
