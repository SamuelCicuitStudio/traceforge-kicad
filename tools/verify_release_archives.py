"""Check the independent standalone installers and release checksums."""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$',
                    (root/'pyproject.toml').read_text(encoding='utf-8'), re.M).group(1)
folder = f'TraceForge-{version}'
archives = {kind:root/'dist'/f'{folder}-KiCad10-{kind}.zip'
            for kind in ('Windows','macOS','PCM')}
assert all(path.is_file() for path in archives.values())
for kind,path in archives.items():
    with zipfile.ZipFile(path) as bundle:
        assert bundle.testzip() is None,path
        members = set(bundle.namelist())
        if kind == 'PCM':
            assert {'metadata.json','plugins/__init__.py'} <= members
        else:
            base = folder+'/'
            assert base+'native_bridge/__init__.py' in members
            assert base+'native_bridge/python_runtime.py' in members
            win = base+'tools/install_native_bridge.ps1'
            mac = base+'tools/install_native_bridge_macos.sh'
            expected = (True,False) if kind == 'Windows' else (False,True)
            assert (win in members,mac in members) == expected
            if kind == 'macOS':
                assert bundle.getinfo(mac).external_attr >> 16 & 0o111
checksums = dict(line.split('  ',1) for line in
                 (root/'dist/SHA256SUMS.txt').read_text(encoding='utf-8').splitlines())
assert set(checksums) == {
    hashlib.sha256(path.read_bytes()).hexdigest() for path in archives.values()
}
assert set(checksums.values()) == {path.name for path in archives.values()}
print(f'PASS: {len(archives)} independent release archives and checksums for {version}')
