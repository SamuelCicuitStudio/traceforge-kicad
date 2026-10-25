"""Build a KiCad Plugin and Content Manager archive and submission metadata."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / 'icons' / 'traceforge-light-64.png'
METADATA = ROOT / 'pcm' / 'metadata.json'
RELEASE_BASE = 'https://github.com/SamuelCicuitStudio/traceforge-kicad/releases/download'


def files():
    """Map repository sources to their PCM archive paths."""
    paths = {'plugins/__init__.py': ROOT / 'native_bridge' / '__init__.py',
             'resources/icon.png': ICON}
    for name in ('traceforge_action.py', 'highlight_net_chain_action.py',
                 'signal_path_analyzer_action.py'):
        paths[f'plugins/{name}'] = ROOT / name
    for source in (ROOT / 'native_bridge').glob('*.py'):
        if source.name != '__init__.py':
            paths[f'plugins/{source.name}'] = source
    for source in (ROOT / 'signal_path_analyzer').glob('*.py'):
        paths[f'plugins/signal_path_analyzer/{source.name}'] = source
    for source in (ROOT / 'icons').glob('*.png'):
        if source.name.endswith(('-24.png', '-48.png')):
            paths[f'plugins/icons/{source.name}'] = source
    if any(not source.is_file() or source.is_symlink() for source in paths.values()):
        raise ValueError('PCM package has a missing or symlinked source')
    return paths


def main():
    metadata = json.loads(METADATA.read_text(encoding='utf-8'))
    if len(metadata['versions']) != 1:
        raise ValueError('Packaged PCM metadata must have exactly one version')
    version = metadata['versions'][0]['version']
    project = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', project, re.MULTILINE)
    if not match or match.group(1) != version:
        raise ValueError('PCM metadata and project versions differ')
    if 'download_url' in metadata['versions'][0] or 'download_sha256' in metadata['versions'][0]:
        raise ValueError('Download fields belong in submission metadata, not the archive')

    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    name = f'TraceForge-{version}-KiCad10-PCM.zip'
    archive = output / name
    paths = files()
    content = {'metadata.json': METADATA.read_bytes()}
    content.update({name: path.read_bytes() for name, path in paths.items()})
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for member, data in sorted(content.items()):
            info = zipfile.ZipInfo(member, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() or set(bundle.namelist()) != set(content):
            raise ValueError('PCM archive failed integrity or allowlist validation')
        install_size = sum(entry.file_size for entry in bundle.infolist())

    submission = json.loads(METADATA.read_text(encoding='utf-8'))
    release = submission['versions'][0]
    release.update(download_url=f'{RELEASE_BASE}/v{version}/{name}',
                   download_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                   download_size=archive.stat().st_size,
                   install_size=install_size)
    package_dir = output / 'pcm-submission' / submission['identifier']
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / 'metadata.json').write_text(
        json.dumps(submission, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (package_dir / 'icon.png').write_bytes(ICON.read_bytes())
    print(f'Built {name}: {len(content)} files, {archive.stat().st_size} bytes')
    print(f"SHA256 {release['download_sha256']}")
    return archive


if __name__ == '__main__':
    main()
