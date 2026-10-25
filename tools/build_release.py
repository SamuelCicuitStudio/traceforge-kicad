"""Build a standalone Windows/KiCad distribution from an explicit public-file allowlist."""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_files():
    paths = [ROOT / name for name in (
        'README.md', 'LICENSE', 'pyproject.toml', 'CHANGELOG.md',
        'traceforge_action.py', 'highlight_net_chain_action.py',
        'signal_path_analyzer_action.py',
        'tools/install_native_bridge.ps1', 'docs/NATIVE-BOARD-ACCESS.md',
        'docs/VIA-STITCHING-TESTING.md', 'docs/FEATURE-SCOPE.md',
        'docs/BGA-FANOUT.md', 'docs/VIA-FENCING.md',
        'docs/SELECTED-ENDPOINTS.md', 'docs/TRACE-CLEANUP.md',
    )]
    for directory in ('signal_path_analyzer', 'native_bridge'):
        paths.extend((ROOT / directory).glob('*.py'))
    paths.append(ROOT / 'docs' / 'RELEASE-NOTES.md')
    paths.extend((ROOT / 'docs' / 'screenshots').glob('*.png'))
    paths.extend((ROOT / 'icons').glob('*.png'))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Missing or symlinked release input: {path.relative_to(ROOT)}')
    return sorted(paths)


def main():
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$',
                      (ROOT / 'pyproject.toml').read_text(encoding='utf-8'), re.MULTILINE)
    if not match:
        raise ValueError('A semantic project version is required.')
    version = match.group(1)
    folder = f'TraceForge-{version}'
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    archive = output / f'{folder}-KiCad10-Windows.zip'
    files = release_files()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            info = zipfile.ZipInfo(f'{folder}/{path.relative_to(ROOT).as_posix()}',
                                   date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip():
            raise ValueError('Release archive CRC validation failed.')
        expected = {f'{folder}/{path.relative_to(ROOT).as_posix()}' for path in files}
        if set(bundle.namelist()) != expected:
            raise ValueError('Release archive differs from its allowlist.')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = output / 'SHA256SUMS.txt'
    checksum.write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'Built {archive.name}: {len(files)} public files, {archive.stat().st_size} bytes')
    print(f'SHA256 {digest}')


if __name__ == '__main__':
    main()
