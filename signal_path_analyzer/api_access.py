"""Serialize shared IPC operations and retry only explicit KiCad busy responses."""
from __future__ import annotations

import logging
import threading
import time


def is_busy(error: Exception) -> bool:
    try:
        from kipy.errors import ApiError
        from kipy.proto.common import ApiStatusCode
    except ImportError:
        return False

    return isinstance(error, ApiError) and error.code == ApiStatusCode.AS_BUSY


def trace_call(label, fn):
    """Record the exact IPC stage, including the error code and elapsed time."""
    started = time.monotonic()
    logging.info("IPC start: %s", label)
    try:
        result = fn()
    except Exception as exc:
        logging.error("IPC failed: %s code=%s elapsed=%.3fs error=%s", label,
                      getattr(exc, "code", None), time.monotonic() - started, exc)
        raise
    logging.info("IPC done: %s elapsed=%.3fs", label, time.monotonic() - started)
    return result


class ApiAccess:
    def __init__(self):
        self.lock = threading.RLock()

    def call(self, fn, retries=0):
        with self.lock:
            for attempt in range(retries + 1):
                try:
                    return fn()
                except Exception as exc:
                    if not is_busy(exc) or attempt == retries:
                        raise
                    logging.info("KiCad busy; retry %s/%s", attempt + 1, retries)
                    time.sleep(min(0.1 * (attempt + 1), 0.5))
