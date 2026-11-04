"""Final artifact checks and CAM attachment packing for export_package.py."""
import hashlib
import json
import re
import zipfile
from pathlib import Path


def unresolved_document_placeholders(output: Path) -> list[str]:
    unresolved = []
    for document in output.rglob('*.md'):
        placeholders = sorted(set(re.findall(r'\{\{[^{}]+\}\}', document.read_text(encoding='utf-8', errors='replace'))))
        if placeholders:
            unresolved.append(f'{document.relative_to(output)}: {", ".join(placeholders)}')
    return unresolved


def finalize(c, info):
    errors = []
    non_cpl_refs = getattr(c, 'non_cpl_refs', None)
    if non_cpl_refs is None:
        config = c.project / 'tools' / 'export_config_rev_b.json'
        non_cpl_refs = set(json.loads(config.read_text(encoding='utf-8')).get('non_cpl_refs', [])) \
            if config.is_file() else set()
    if 'non_cpl_hardware' not in info:
        info['non_cpl_hardware'] = sorted(set(info['bom']['refs']) & non_cpl_refs)
        info['bom_not_in_cpl'] = sorted(set(info.get('bom_not_in_cpl', [])) - non_cpl_refs)
    for key in ('bom_not_in_cpl', 'cpl_not_in_bom'):
        if info.get(key):
            errors.append(key + ': ' + ', '.join(info[key]))
    if info['bom'].get('missing_mpn'):
        errors.append('Missing MPN: ' + ', '.join(info['bom']['missing_mpn']))
    if len(info['bom']['refs']) != len(set(info['bom']['refs'])):
        errors.append('Duplicate BOM references')
    if sum(info['placement'].values()) != info['bom']['parts'] - len(info.get('non_cpl_hardware', [])):
        errors.append('Placement count differs from BOM part count')
    if set(info.get('non_cpl_hardware', [])) != non_cpl_refs:
        errors.append('Declared non-CPL hardware references missing from BOM')
    unresolved_docs = unresolved_document_placeholders(c.out)
    if unresolved_docs:
        errors.append('Unresolved ordering/document placeholders: ' + '; '.join(unresolved_docs))
    archive = c.dirs['fab'] / f'{c.prefix}-Gerber.zip'
    attachments = []
    # Include the actual documents, not a checklist promising absent attachments.
    for p in c.out.rglob('*'):
        if not p.is_file():
            continue
        if ('Ordering' in str(p.relative_to(c.out)) or 'ordering' in str(p.relative_to(c.out))
                or 'Fabrication-Drawing' in p.name or 'STACKUP' in p.name):
            if p.suffix.lower() in {'.pdf', '.md', '.csv', '.txt'}:
                attachments.append(p)
    with zipfile.ZipFile(archive, 'a', zipfile.ZIP_DEFLATED) as z:
        for p in attachments:
            member = 'CAM-Notes/' + p.relative_to(c.out).as_posix()
            if member not in z.namelist():
                z.write(p, member)
        names = set(z.namelist())
        jobs = [n for n in names if n.endswith('.gbrjob')]
        if len(jobs) != 1:
            errors.append('Expected one Gerber job file')
        for job in jobs:
            for f in json.loads(z.read(job)).get('FilesAttributes', []):
                if f['Path'] not in names:
                    errors.append('Missing Gerber job member: ' + f['Path'])
        if not any('PTH' in n and 'NPTH' not in n and n.endswith('.drl') for n in names):
            errors.append('Missing PTH drill')
        if not any('NPTH' in n and n.endswith('.drl') for n in names):
            errors.append('Missing NPTH drill')
        if not attachments:
            errors.append('No CAM ordering/fabrication notes supplied; configure docs_dir')
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            errors.append('Corrupt fabrication archive')
    info['package_preflight'] = {'errors': errors,
        'cam_attachments': [p.relative_to(c.out).as_posix() for p in attachments],
        'release_status': 'HOLD' if errors or any(info['reports'][k]['errors'] for k in ('erc','drc'))
                          else 'Engineering/CAM approval not established by export checks'}
    (c.out / 'EXPORT-FACTS.json').write_text(json.dumps(info, indent=2, default=str)+'\n', encoding='utf-8')
    sums = [hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(c.out).as_posix()
            for p in sorted(c.out.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS.txt']
    (c.out / 'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n', encoding='utf-8')
    if errors:
        raise RuntimeError('Manufacturing package preflight failed:\n'+'\n'.join(errors))
