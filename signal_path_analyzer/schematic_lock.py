"""Conservative stale KiCad schematic-lock checks without deleting lock files."""

from __future__ import annotations

import csv
import io
import json
import os
import socket
import subprocess


def schematic_editor_running():
    """False only after a successful local Windows process enumeration."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode or not result.stdout.strip():
            return None
        rows = list(csv.reader(io.StringIO(result.stdout)))
        processes = [row[0].casefold() for row in rows if len(row) >= 2 and row[1].isdigit()]
        if not processes:
            return None
        return "eeschema.exe" in processes
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def blocks(lock, editor_running):
    try:
        owner = json.loads(lock.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return True
    host = str(owner.get("hostname", "")).casefold()
    local = {
        socket.gethostname().casefold(),
        socket.getfqdn().casefold(),
        os.environ.get("COMPUTERNAME", "").casefold(),
    } - {""}
    # A remote or unknown lock may represent another workstation's active editor.
    # With any local schematic editor running, retain the guard rather than guess
    # which project it owns. The lock need not contain a PID (KiCad 10 does not).
    return not (host in local and editor_running is False)
