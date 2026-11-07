"""Cooperative cancellation across the panel worker and KiCad GUI process."""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path


class OperationCancelled(RuntimeError):
    pass


def check_file(path):
    if path and Path(path).exists():
        raise OperationCancelled('Operation cancelled; no board changes were applied.')


def check_payload(payload):
    check_file(payload.get('cancel_file'))


def checker(path):
    last = 0.0

    def check():
        nonlocal last
        if path and time.monotonic()-last >= .05:
            last = time.monotonic()
            check_file(path)

    check()
    return check


class Cancellation:
    def __init__(self):
        self._temp = tempfile.TemporaryDirectory(prefix='traceforge-cancel-')
        self.path = str(Path(self._temp.name)/'cancel')
        self._lock = threading.Lock()
        self.cancelled = False
        self.closed = False

    def cancel(self):
        with self._lock:
            if self.closed:
                return False
            self.cancelled = True
            Path(self.path).touch()
            return True

    def check(self):
        check_file(self.path)

    def close(self):
        with self._lock:
            self.closed = True
            self._temp.cleanup()
