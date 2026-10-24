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
        self.board_file = str(board_file)
        self.endpoint = endpoint

    def call(self, operation, **payload):
        request = dict(token=self.endpoint['token'], board=self.board_file,
                       operation=operation, payload=payload)
        with socket.create_connection(('127.0.0.1', self.endpoint['port']), timeout=1) as conn:
            conn.settimeout(6)
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


def connect(board_file):
    for path in REGISTRY.glob('*.json'):
        try:
            link = NativeBridge(board_file, json.loads(path.read_text(encoding='utf-8')))
            link.call('info')
            return link
        except (OSError, ValueError, KeyError, RuntimeError):
            continue
    return None
