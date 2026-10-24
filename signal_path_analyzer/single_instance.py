"""One TraceForge panel per user: a second launch asks the running panel to come to the front.

The listener thread never writes to stdout/stderr and stops cleanly: a daemon thread that prints
while the interpreter shuts down kills the process (KiCad showed "_enter_buffered_busy ... daemon
threads", exit code 0xC0000409).
"""

from __future__ import annotations

import socket
import threading
from typing import Callable, Optional

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


class Listener:
    def __init__(self, port: int, on_activate: Callable[[], None]):
        self.server: Optional[socket.socket] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.server.bind(("127.0.0.1", port))
        self.server.listen(4)
        self.server.settimeout(0.5)
        self.on_activate, self.running = on_activate, True
        self.thread = threading.Thread(target=self._loop, name="traceforge-single-instance")
        self.thread.start()

    def _loop(self) -> None:
        while self.running:
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                with conn:
                    conn.settimeout(1.0)
                    if conn.recv(64) == _MAGIC:
                        conn.sendall(b"ok\n")
                        self.on_activate()
            except OSError:
                continue

    def stop(self) -> None:
        self.running = False
        if self.server is not None:
            self.server.close()
            self.server = None
        self.thread.join(timeout=2)


def listen(port: int, on_activate: Callable[[], None]) -> Listener:
    return Listener(port, on_activate)
