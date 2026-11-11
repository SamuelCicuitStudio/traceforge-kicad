"""Offline checks for standalone panel-Python selection."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

module_path = Path(__file__).resolve().parents[1] / 'native_bridge/python_runtime.py'
spec = importlib.util.spec_from_file_location('traceforge_python_runtime_check', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    chosen = root / 'Mac Python'
    chosen.write_text('fixture', encoding='utf-8')
    (root/'traceforge-python.txt').write_text(str(chosen)+'\n', encoding='utf-8')
    assert module.panel_python(root, '/irrelevant/pcbnew.py', platform='posix') == chosen
    chosen.unlink()
    try:
        module.panel_python(root, '/irrelevant/pcbnew.py', platform='posix')
    except FileNotFoundError as exc:
        assert 'Rerun the installer' in str(exc)
    else:
        raise AssertionError('Missing configured interpreter was accepted')
print('PASS: configured panel Python and missing-path rejection')
