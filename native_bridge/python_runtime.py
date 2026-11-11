"""Find the external wxPython interpreter used by the TraceForge panel."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def panel_python(root: Path, pcbnew_file: str, *, platform: str | None = None) -> Path:
    platform = platform or os.name
    configured = root / 'traceforge-python.txt'
    if configured.is_file():
        candidate = Path(configured.read_text(encoding='utf-8').strip()).expanduser()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(
            f'TraceForge panel Python no longer exists: {candidate}. Rerun the installer.'
        )
    if platform == 'nt':
        candidate = Path(pcbnew_file).resolve().parents[2] / 'python.exe'
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f'KiCad Python was not found at {candidate}.')
    candidate = os.environ.get('TRACEFORGE_PYTHON') or shutil.which('python3')
    if not candidate:
        raise FileNotFoundError(
            'No Python 3 found for the TraceForge panel. '
            'Run the macOS installer with --python PATH.'
        )
    candidate = Path(candidate).expanduser().resolve()
    if not candidate.is_file():
        raise FileNotFoundError(
            f'TraceForge panel Python was not found at {candidate}.'
        )
    result = subprocess.run(
        [str(candidate), '-c', 'import wx'], capture_output=True, timeout=8, check=False
    )
    if result.returncode:
        raise RuntimeError(
            'TraceForge panel Python cannot import wxPython. '
            'Run the macOS installer with --python PATH.'
        )
    return candidate
