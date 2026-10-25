"""Authenticated localhost transport to the KiCad 10 in-process board helper."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from .chains import NetGeometry, TrackSeg, ViaHop

REGISTRY = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TraceForge' / 'native-bridge'
LIMIT = 32 * 1024 * 1024


class NativeBridge:
    def __init__(self, board_file, endpoint):
        self.board_file = str(board_file) if board_file is not None else None
        self.endpoint = endpoint

    def call(self, operation, **payload):
        request = dict(token=self.endpoint['token'], board=self.board_file,
                       operation=operation, payload=payload)
        with socket.create_connection(('127.0.0.1', self.endpoint['port']), timeout=1) as conn:
            conn.settimeout(125 if operation.startswith(
                ('stitch_', 'fanout_', 'tracefence_')) else 6)
            conn.sendall(json.dumps(request).encode('utf-8') + b'\n')
            with conn.makefile('rb') as stream:
                raw = stream.readline(LIMIT + 1)
        if len(raw) > LIMIT or not raw.endswith(b'\n'):
            raise RuntimeError('Invalid native helper response')
        response = json.loads(raw)
        if response.get('wrong_board'):
            raise ValueError('Native helper belongs to a different open board')
        if 'error' in response:
            raise RuntimeError(response['error'])
        return response['result']

    def snapshot(self, nets):
        return {n: NetGeometry(g['netclass'], [TrackSeg(*r) for r in g['tracks']],
                               [ViaHop(tuple(r)) for r in g['vias']], g['die_mm'])
                for n, g in self.call('snapshot', nets=nets).items()}


def connect(board_file=None, endpoint_file=None):
    paths = [Path(endpoint_file)] if endpoint_file else list(REGISTRY.glob('*.json'))
    matches = []
    for path in paths:
        try:
            link = NativeBridge(board_file, json.loads(path.read_text(encoding='utf-8')))
            info = link.call('info')
            link.board_file = info['board']
            matches.append(link)
        except (OSError, ValueError, KeyError, RuntimeError):
            continue
    if len(matches) > 1:
        raise RuntimeError('Multiple PCB Editors are open. Launch TraceForge from the intended '
                           "board's native toolbar button.")
    return matches[0] if matches else None


def require_native():
    link = connect(os.environ.get('TRACEFORGE_BOARD_FILE'),
                   os.environ.get('TRACEFORGE_NATIVE_ENDPOINT'))
    if link is None:
        raise RuntimeError('TraceForge native helper is not available. Install it with '
                           'tools/install_native_bridge.ps1, restart PCB Editor, then use '
                           'the TraceForge native toolbar button. No IPC fallback is used.')
    return link
