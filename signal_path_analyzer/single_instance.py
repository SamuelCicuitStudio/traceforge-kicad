"""One TraceForge panel per user: a second launch asks the running panel to come to the front.

The listener thread never writes to stdout/stderr and stops cleanly: a daemon thread that prints
while the interpreter shuts down kills the process (KiCad showed "_enter_buffered_busy ... daemon
threads", exit code 0xC0000409).
"""

from __future__ import annotations

import socket
import threading
from typing import Callable, Optional

from . import NATIVE_BUILD_ID, __version__
from .workspaces import tool_id

PORT = 47231  # localhost only
_MAGIC = b"traceforge:front\n"
_TAB_MAGIC = b"traceforge:tab:"
_VERSION_MAGIC = b"traceforge:version\n"


class ExistingPanelVersionError(RuntimeError):
    """A running panel belongs to a different installed build."""


def try_activate_existing(port: int = PORT, tab: Optional[int] = None) -> bool:
    """True when a panel is already running (it was asked to come to the front)."""

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5) as s:
            s.sendall(_VERSION_MAGIC)
            reply = s.recv(128)
    except OSError:
        return False
    expected = f'version:{__version__};build:{NATIVE_BUILD_ID}\n'.encode()
    if reply != expected:
        running = reply.decode(errors='replace').strip() if reply else 'an older build'
        raise ExistingPanelVersionError(
            f'TraceForge {__version__} found an already running panel ({running}). '
            'Close the old TraceForge window and every KiCad window, then reopen the board.')
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5) as s:
            target = tab if isinstance(tab, int) else tool_id(tab) if tab is not None else None
            command = _MAGIC if target is None else _TAB_MAGIC + f'{target}\n'.encode()
            s.sendall(command)
            return s.recv(3) == b"ok\n"
    except OSError:
        return False


class Listener:
    def __init__(self, port: int, on_activate: Callable[[Optional[int]], None]):
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
                    command = conn.recv(64)
                    if command == _VERSION_MAGIC:
                        conn.sendall(f'version:{__version__};build:{NATIVE_BUILD_ID}\n'.encode())
                    elif command == _MAGIC:
                        conn.sendall(b"ok\n")
                        self.on_activate(None)
                    elif command.startswith(_TAB_MAGIC):
                        value = command[len(_TAB_MAGIC):].strip()
                        try:
                            target = tool_id(value.decode('ascii'))
                        except (ValueError, UnicodeError):
                            continue
                        conn.sendall(b"ok\n")
                        self.on_activate(int(value) if value.isdigit() else target)
            except OSError:
                continue

    def stop(self) -> None:
        self.running = False
        if self.server is not None:
            self.server.close()
            self.server = None
        self.thread.join(timeout=2)


def listen(port: int, on_activate: Callable[[Optional[int]], None]) -> Listener:
    return Listener(port, on_activate)
