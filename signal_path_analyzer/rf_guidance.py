"""Wavelength spacing estimate, not a coplanar impedance or antenna solver."""
import json
import math
import re
from pathlib import Path


def spacing(frequency_mhz, permittivity, division=20):
    frequency_mhz, permittivity = float(frequency_mhz), float(permittivity)
    if (not math.isfinite(frequency_mhz) or frequency_mhz <= 0 or
            not math.isfinite(permittivity) or permittivity < 1):
        raise ValueError('Frequency must be positive and permittivity must be at least 1.')
    if division not in (10, 20):
        raise ValueError('Choose wavelength / 10 or wavelength / 20.')
    wavelength = 299792.458 / (frequency_mhz * math.sqrt(permittivity))
    if not math.isfinite(wavelength) or wavelength <= 0:
        raise ValueError('Frequency is outside the supported numeric range.')
    return dict(wavelength_mm=wavelength, spacing_mm=wavelength / division)


def saved_dielectrics(board_file):
    """Read dielectric rows only inside the saved board's balanced stackup expression."""
    text = Path(board_file).read_text(encoding='utf-8')
    tokens = re.finditer(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text)
    active, depth, levels, root = False, 0, [], None
    previous = None
    for match in tokens:
        token = match.group()
        if not active:
            if token == 'stackup' and previous == '(':
                active, depth, root = True, 1, ['stackup']
                levels = [root]
            previous = token
            continue
        if token == '(':
            child = []
            levels[-1].append(child)
            levels.append(child)
            depth += 1
        elif token == ')':
            depth -= 1
            levels.pop()
            if depth == 0:
                break
        else:
            levels[-1].append(json.loads(token) if token.startswith('"') else token)
    if not active or depth:
        return []
    layers = [row for row in root[1:] if isinstance(row, list) and row[0] == 'layer']
    result = []
    for row in layers:
        values = {p[0]: p[1] for p in row[2:] if isinstance(p, list) and len(p) > 1}
        if 'epsilon_r' in values and values.get('type', '').lower() != 'copper':
            er, height = float(values['epsilon_r']), float(values.get('thickness', 0))
            if math.isfinite(er) and er >= 1 and math.isfinite(height) and height >= 0:
                result.append(dict(name=row[1], epsilon_r=er, thickness_mm=height))
    return result
