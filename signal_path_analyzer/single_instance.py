"""One TraceForge panel per user: a second launch asks the running panel to come to the front."""

from __future__ import annotations

import socket
import threading
from typing import Callable

PORT = 47231  # localhost only
_MAGIC = b"traceforge:front\n"


def try_activate_existing(port: int = PORT) -> bool:
    """True when a panel is already running (it was asked to come to the front)."""

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5) as s:
            s.sendall(_MAGIC)
            return s.recv(3) == b"ok\n"
    except OSError:
        return False


def listen(port: int, on_activate: Callable[[], None]) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1) if hasattr(
        socket, "SO_EXCLUSIVEADDRUSE") else None
    server.bind(("127.0.0.1", port))
    server.listen(4)

    def loop():
        while True:
            conn, _ = server.accept()
            with conn:
                if conn.recv(64) == _MAGIC:
                    conn.sendall(b"ok\n")
                    on_activate()

    threading.Thread(target=loop, daemon=True).start()
