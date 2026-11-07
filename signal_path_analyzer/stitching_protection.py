"""User-facing assembly protection policy, independent of copper net clearance."""
from __future__ import annotations

import fnmatch
import re


def is_fiducial(reference, value, library_id):
    return (bool(re.match(r'^FID(?:\d|[_-]|$)', reference, re.I)) or
            'fiducial' in (str(value) + ' ' + str(library_id)).casefold())


def critical_reference(reference, patterns):
    return any(fnmatch.fnmatchcase(reference.upper(), pattern.strip().upper())
               for pattern in patterns.split(',') if pattern.strip())


def protection_kind(reference, value, library_id, patterns):
    if is_fiducial(reference, value, library_id):
        return 'fiducial optical area'
    if critical_reference(reference, patterns):
        return 'critical footprint'
    return 'component courtyard'
