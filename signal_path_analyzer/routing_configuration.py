"""Saved board construction and KiCad-computed routing geometry; no default estimates."""
import json
import re
from pathlib import Path

from .profiles import _LAYER, _THICK


def routing_configuration(board_file):
    board = Path(board_file)
    text = board.read_text(encoding='utf-8')
    project = board.with_suffix('.kicad_pro')
    data = json.loads(project.read_text(encoding='utf-8')) if project.exists() else {}
    start = text.find('(stackup')
    layers = []
    if start >= 0:
        for match in _LAYER.finditer(text, start):
            name, body = match.group(1), match.group(2)
            thickness = _THICK.search(body)
            er = re.search(r'\(epsilon_r ([\d.]+)', body)
            material = re.search(r'\(material "([^"\n]+)"', body)
            if name.endswith('.Cu') or name.startswith('dielectric '):
                layers.append(dict(name=name,
                                   thickness=thickness.group(1) if thickness else 'unset',
                                   er=er.group(1) if er else '',
                                   material=material.group(1) if material else ''))
            if name == 'B.Cu':
                break
    construction = ' | '.join(
        f"{x['name']}: {x['thickness']} mm"
        + (f" {x['material']}" if x['material'] else '')
        + (f" Er={x['er']}" if x['er'] else '') for x in layers)
    selection_file = board.parent / 'pcb-preparation' / 'stackup-selection.json'
    if not selection_file.exists():
        selection_file = board.parent / 'pcb-preparation' / 'pcbway-stackup-selection.json'
    if selection_file.exists():
        selection = json.loads(selection_file.read_text(encoding='utf-8')).get('selection', {})
        construction = str(selection.get('id', 'Selected stackup')) + ' | ' + construction
    classes = data.get('net_settings', {}).get('classes', [])
    rows = []
    for profile in data.get('tuning_profiles', {}).get('tuning_profiles_impedance_geometric', []):
        name = profile.get('profile_name', '')
        assigned = ', '.join(c['name'] for c in classes if c.get('tuning_profile') == name)
        differential = profile.get('type') == 1
        for entry in profile.get('layer_entries', []):
            refs = [entry.get(k) for k in ('top_reference_layer', 'bottom_reference_layer')]
            refs = [r for r in refs if r and r != 'UNDEFINED']
            def mm(key, entry=entry):
                value = entry.get(key)
                return f'{value / 1e6:.4f}' if value and value > 0 else 'NOT COMPUTED'
            rows.append([name, assigned or '(unassigned)', 'DIFF' if differential else 'SE / RF',
                         str(profile.get('target_impedance', 'unset')),
                         entry.get('signal_layer', 'unset'), ' / '.join(refs) or 'UNSET',
                         mm('width'), mm('diff_pair_gap') if differential else 'n/a',
                         'Saved profile geometry'])
    names = {p.get('profile_name') for p in data.get('tuning_profiles', {}).get(
        'tuning_profiles_impedance_geometric', [])}
    for cls in classes:
        if cls.get('tuning_profile') not in names:
            rows.append(['NO COMPUTED PROFILE', cls['name'], 'Netclass only', 'unset', 'unset',
                         'unset', str(cls.get('track_width', 'unset')),
                         str(cls.get('diff_pair_gap', 'unset')), 'Settings only; NOT computed'])
    return dict(stackup=construction or 'STACKUP NOT CONFIGURED', rows=rows,
                source=str(board), note='Last saved board/project. Width = track width; '
                'gap = edge-to-edge pair gap. Profile geometry is KiCad saved output, '
                'not a new field-solver calculation; recompute profiles after a stackup change. '
                'Save changes and refresh to reload.')
