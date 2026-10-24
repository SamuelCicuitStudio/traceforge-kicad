"""KiCad 10 in-process helper. All board access executes on KiCad's wx main thread."""
from __future__ import annotations

import atexit
import hmac
import json
import os
import re
import secrets
import socket
import threading
from pathlib import Path

import pcbnew
import wx

LIMIT = 32 * 1024 * 1024
REGISTRY = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TraceForge' / 'native-bridge'


def board_path(board):
    return os.path.normcase(os.path.abspath(board.GetFileName()))


class TransientHighlight:
    """Keep UUIDs and previous flags, never pointers to potentially deleted board items."""
    def __init__(self):
        self.board = None
        self.previous = {}

    def clear(self, board, items):
        if self.board == board_path(board):
            for item in items:
                old = self.previous.get(item.m_Uuid.AsString())
                if old is not None:
                    if old[0]:
                        item.SetSelected()
                    else:
                        item.ClearSelected()
                    if old[1]:
                        item.SetBrightened()
                    else:
                        item.ClearBrightened()
        self.board, self.previous = None, {}

    def apply(self, board, items, nets, refs):
        self.clear(board, items)
        self.board = board_path(board)
        chosen = []
        for item in items:
            match = (item.GetReference() in refs if isinstance(item, pcbnew.FOOTPRINT) else
                     item.GetNetname().replace('{slash}', '/') in nets)
            if match:
                self.previous[item.m_Uuid.AsString()] = (item.IsSelected(), item.IsBrightened())
                item.SetSelected()
                item.SetBrightened()
                chosen.append(item)
        return chosen


_highlights = TransientHighlight()


def board_items(board):
    result = list(board.GetTracks())
    for fp in board.GetFootprints():
        result.extend(fp.Pads())
        result.append(fp)
    return result


class CanvasInteractionFilter(wx.EventFilter):
    def FilterEvent(self, event):
        kinds = (wx.EVT_LEFT_DOWN.typeId, wx.EVT_RIGHT_DOWN.typeId, wx.EVT_MIDDLE_DOWN.typeId,
                 wx.EVT_KEY_DOWN.typeId)
        if _highlights.previous and event.GetEventType() in kinds:
            window = event.GetEventObject()
            if isinstance(window, wx.Window):
                frame = wx.GetTopLevelParent(window)
                if isinstance(frame, wx.Frame) and frame.GetTitle().endswith('PCB Editor'):
                    board = pcbnew.GetBoard()
                    if board is not None:
                        _highlights.clear(board, board_items(board))
                        pcbnew.Refresh()
        return wx.EventFilter.Event_Skip


def zoom_to_items(board, chosen):
    """Use the editor's native zoom presets and focus helper, without the IPC server."""
    if not chosen:
        return False
    frame = next((w for w in wx.GetTopLevelWindows() if isinstance(w, wx.Frame)
                  and w.GetTitle().endswith('PCB Editor')), None)
    if frame is None:
        return False
    control = frame.FindWindowById(pcbnew.ID_ON_ZOOM_SELECT)
    if control is None or not hasattr(control, 'SetSelection'):
        return False

    def preset(index):
        control.SetSelection(index)
        event = wx.CommandEvent(wx.EVT_CHOICE.typeId, control.GetId())
        event.SetEventObject(control)
        control.GetEventHandler().ProcessEvent(event)

    # Calibrate to the same board-edge extents that KiCad uses for Zoom Auto.
    preset(0)
    match = re.search(r'[0-9]+(?:[.,][0-9]+)?', frame.GetStatusBar().GetStatusText(1))
    if not match:
        return False
    scale = float(match.group().replace(',', '.'))
    box = chosen[0].GetBoundingBox()
    for item in chosen[1:]:
        box.Merge(item.GetBoundingBox())
    extents = board.ComputeBoundingBox(True)
    if not extents.GetWidth() or not extents.GetHeight():
        extents = board.ComputeBoundingBox()
    size = frame.GetClientSize()
    width, height = max(size.width, 1), max(size.height, 1)
    before = max(extents.GetWidth() / width, extents.GetHeight() / height)
    after = max(box.GetWidth() / width, box.GetHeight() / height, 1e6 / min(width, height))
    desired = scale * before / (after * 1.5)
    options = []
    for index in range(1, control.GetCount()):
        value = re.search(r'[0-9]+(?:[.,][0-9]+)?', control.GetString(index))
        if value:
            value = float(value.group().replace(',', '.'))
            if value <= desired:
                options.append((value, index))
    if options:
        preset(max(options)[1])
    # An unregistered pad provides a focus point; it is never added to the board.
    point = pcbnew.PAD(None)
    point.SetPosition(box.GetCenter())
    pcbnew.FocusOnItem(point)
    return True


def dispatch(board, operation, payload):
    """Called only on the editor thread; no IPC API or file reload is involved."""
    def footprints():
        return list(board.GetFootprints())

    def items():
        result = list(board.GetTracks())
        for fp in footprints():
            result.extend(fp.Pads())
            result.append(fp)
        return result

    if operation == 'info':
        return {'board': board.GetFileName(), 'protocol': 2,
                'features': ['transient_highlight', 'native_zoom']}
    if operation == 'snapshot':
        wanted = set(payload['nets'])
        geometry = {}
        for n in board.GetNetsByNetcode().values():
            name = n.GetNetname().replace('{slash}', '/')
            if name in wanted:
                geometry[name] = dict(netclass=n.GetNetClassName(), tracks=[], vias=[], die_mm=[])
        for tr in board.GetTracks():
            name = tr.GetNetname().replace('{slash}', '/')
            geo = geometry.get(name)
            if geo is None:
                continue
            if isinstance(tr, pcbnew.PCB_VIA):
                geo['vias'].append([pcbnew.LayerName(tr.TopLayer()),
                                    pcbnew.LayerName(tr.BottomLayer())])
            else:
                geo['tracks'].append([pcbnew.LayerName(tr.GetLayer()), tr.GetLength() / 1e6])
        for fp in footprints():
            for pad in fp.Pads():
                geo = geometry.get(pad.GetNetname().replace('{slash}', '/'))
                if geo is not None and pad.GetPadToDieLength():
                    geo['die_mm'].append(pad.GetPadToDieLength() / 1e6)
        return geometry
    if operation == 'selection':
        selected = {it.m_Uuid.AsString(): it for it in pcbnew.GetCurrentSelection()
                    if it.IsSelected()}
        selected.update({it.m_Uuid.AsString(): it for it in items() if it.IsSelected()})
        return [dict(ref=it.GetReference()) if isinstance(it, pcbnew.FOOTPRINT) else
                dict(net=it.GetNetname().replace('{slash}', '/'))
                for it in selected.values() if hasattr(it, 'GetNetname') or
                isinstance(it, pcbnew.FOOTPRINT)]
    if operation in ('clear', 'highlight', 'zoom'):
        live = items()
        if operation == 'clear':
            _highlights.clear(board, live)
            pcbnew.Refresh()
            return 0
        if operation == 'zoom':
            chosen = [it for it in live if it.m_Uuid.AsString() in _highlights.previous]
            if not chosen:
                chosen = [it for it in live if it.IsSelected()]
            return zoom_to_items(board, chosen)
        chosen = _highlights.apply(board, live, set(payload.get('nets', [])),
                                   set(payload.get('refs', [])))
        pcbnew.Refresh()
        if payload.get('zoom', False):
            zoom_to_items(board, chosen)
        return len(chosen)
    if operation == 'parts':
        return [(fp.GetReference(), fp.GetValue(),
                 {p.GetNumber(): p.GetNetname().replace('{slash}', '/') for p in fp.Pads()})
                for fp in footprints()]
    if operation == 'positions':
        pads, parts = {}, {}
        for fp in footprints():
            ref = fp.GetReference()
            parts[ref] = [fp.GetPosition().x / 1e6, fp.GetPosition().y / 1e6]
            for pad in fp.Pads():
                pads[f'{ref}.{pad.GetNumber()}'] = [pad.GetPosition().x / 1e6,
                                                  pad.GetPosition().y / 1e6]
        return [pads, parts]
    if operation == 'netclasses':
        return {n.GetNetname().replace('{slash}', '/'): n.GetNetClassName()
                for n in board.GetNetsByNetcode().values()}
    if operation == 'names':
        return {n.GetNetname().replace('{slash}', '/'): n.GetNetname()
                for n in board.GetNetsByNetcode().values()}
    raise ValueError(f'Unsupported native operation: {operation}')


class Server:
    def __init__(self):
        self.filter = CanvasInteractionFilter()
        wx.EvtHandler.AddFilter(self.filter)
        self.token = secrets.token_hex(32)
        self.socket = socket.socket()
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(2)
        self.socket.settimeout(0.5)
        self.stop_event = threading.Event()
        REGISTRY.mkdir(parents=True, exist_ok=True)
        self.file = REGISTRY / f'{os.getpid()}.json'
        self.file.write_text(json.dumps({'port': self.socket.getsockname()[1], 'token': self.token,
                                        'pid': os.getpid()}), encoding='utf-8')
        self.thread = threading.Thread(target=self.serve, name='traceforge-native', daemon=True)
        self.thread.start()
        atexit.register(self.stop)

    def serve(self):
        while not self.stop_event.is_set():
            try:
                conn, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                with conn:
                    conn.settimeout(3)
                    with conn.makefile('rb') as stream:
                        raw = stream.readline(LIMIT + 1)
                    if len(raw) > LIMIT or not raw.endswith(b'\n'):
                        continue
                    request = json.loads(raw)
                    if not hmac.compare_digest(str(request.get('token', '')), self.token):
                        continue
                    done = threading.Event()
                    state = {'cancelled': False}
                    wx.CallAfter(self.execute, request, state, done)
                    if not done.wait(5):
                        state['cancelled'] = True
                        reply = {'error': 'PCB Editor did not service the native request in time'}
                    else:
                        reply = state['reply']
                    conn.sendall(json.dumps(reply).encode('utf-8') + b'\n')
            except (OSError, ValueError):
                continue

    def execute(self, request, state, done):
        if state['cancelled'] or self.stop_event.is_set():
            return
        try:
            board = pcbnew.GetBoard()
            if board is None or not board.GetFileName():
                raise ValueError('No saved board is open')
            if request.get('board') and board_path(board) != os.path.normcase(
                    os.path.abspath(request['board'])):
                state['reply'] = {'wrong_board': True}
            else:
                state['reply'] = {'result': dispatch(board, request['operation'],
                                                     request.get('payload', {}))}
        except Exception as exc:
            state['reply'] = {'error': str(exc)}
        done.set()

    def stop(self):
        self.stop_event.set()
        if wx.IsMainThread() and self.filter is not None:
            wx.EvtHandler.RemoveFilter(self.filter)
            self.filter = None
        self.socket.close()
        self.file.unlink(missing_ok=True)


_server = None


def start():
    global _server
    if _server is None:
        _server = Server()
    return _server
