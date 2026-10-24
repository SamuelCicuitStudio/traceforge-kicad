"""KiCad 10 in-process helper. All board access executes on KiCad's wx main thread."""
from __future__ import annotations

import atexit
import hmac
import json
import os
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
        return {'board': board.GetFileName()}
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
    if operation in ('clear', 'highlight'):
        nets, refs = set(payload.get('nets', [])), set(payload.get('refs', []))
        count = 0
        for it in items():
            it.ClearSelected()
            it.ClearBrightened()
            match = (it.GetReference() in refs if isinstance(it, pcbnew.FOOTPRINT) else
                     it.GetNetname().replace('{slash}', '/') in nets)
            if operation == 'highlight' and match:
                it.SetSelected()
                it.SetBrightened()
                count += 1
        pcbnew.Refresh()
        return count
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
        self.socket.close()
        self.file.unlink(missing_ok=True)


_server = None


def start():
    global _server
    if _server is None:
        _server = Server()
    return _server
