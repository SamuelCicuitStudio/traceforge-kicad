"""Verify the Windows-only PCM release archive without building other platforms."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$',
                    (root / 'pyproject.toml').read_text(encoding='utf-8'), re.M).group(1)
archive = root / 'dist' / f'TraceForge-{version}-KiCad10-PCM.zip'
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    assert {'metadata.json', 'resources/icon.png', 'plugins/__init__.py'} <= set(
        bundle.namelist())
    metadata = json.loads(bundle.read('metadata.json'))
    assert len(metadata['versions']) == 1
    release = metadata['versions'][0]
    assert release['version'] == version
    assert release['status'] == 'stable'
    assert release['platforms'] == ['windows']
    assert release['kicad_version'] == '10.0'
print(f'PASS: Windows PCM {version}, {archive.stat().st_size} bytes')
