"""Serialize native helper operations; failures are never retried automatically."""
from __future__ import annotations

import logging
import threading
import time


def trace_call(label, fn):
    started = time.monotonic()
    logging.info("Native start: %s", label)
    try:
        result = fn()
    except Exception as exc:
        logging.error("Native failed: %s elapsed=%.3fs error=%s", label,
                      time.monotonic() - started, exc)
        raise
    logging.info("Native done: %s elapsed=%.3fs", label, time.monotonic() - started)
    return result


class ApiAccess:
    def __init__(self):
        self.lock = threading.RLock()

    def call(self, fn, retries=0):
        if retries:
            raise ValueError('Automatic retries are disabled for native board operations')
        with self.lock:
            return fn()
