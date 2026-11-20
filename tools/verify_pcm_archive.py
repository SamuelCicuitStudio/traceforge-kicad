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
    source = json.loads((root / 'pcm/metadata.json').read_text(encoding='utf-8'))
    assert release['status'] == source['versions'][0]['status']
    assert release['platforms'] == ['windows']
    assert release['kicad_version'] == '10.0'
    webview = bundle.read('plugins/signal_path_analyzer/webview.html').decode('utf-8')
    assert bundle.read('plugins/signal_path_analyzer/traceforge-logo.png') == (
        root / 'icons' / 'traceforge-dark-48.png'
    ).read_bytes()
    assert "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'" in webview
    for css in re.findall(r'<style\b[^>]*>(.*?)</style>', webview, re.I | re.S):
        assert not re.search(r'@import\b|url\s*\(', css, re.I), 'CSS must use bundled styles and system fonts'
    assert not re.search(r'<(?:link|script|img)\b[^>]*\b(?:href|src)\s*=', webview, re.I), (
        'The WebView shell must render from its bundled HTML'
    )
print(f'PASS: Windows PCM {version}, {archive.stat().st_size} bytes')
