"""Conservative custom-rule bounds for drill-only edits; unknown rules fall back."""
from __future__ import annotations

import json
import re


def rule_bounds(text):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\n]*|[()]|[^\s()]+', text)
    roots, stack = [], []
    for token in tokens:
        if token.startswith('#'):
            continue
        if token == '(':
            node = []
            (stack[-1] if stack else roots).append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError('Unbalanced custom rules.')
            stack.pop()
        else:
            if not stack:
                raise ValueError('Invalid custom rule token.')
            stack[-1].append(json.loads(token) if token.startswith('"') else token)
    if stack:
        raise ValueError('Incomplete custom rules.')
    bounds = {}
    names = {'hole_size', 'annular_width', 'hole_clearance', 'hole_to_hole',
             'physical_hole_clearance', 'edge_clearance'}
    for rule in roots:
        if not rule or rule[0] != 'rule':
            continue
        conditions = [node[1] for node in rule if isinstance(node, list) and
                      node and node[0] == 'condition']
        # Slot/pad-only hole rules cannot apply to an ordinary through via.
        pad_only = any(re.search(r"A\.Type\s*==\s*'Pad'", c) and
                       not re.search(r'\|\||\bor\b', c, re.I) for c in conditions)
        constraints = [n for n in rule if isinstance(n, list) and n and n[0] == 'constraint']
        if pad_only and constraints and all(n[1] in ('hole_size', 'annular_width')
                                           for n in constraints):
            continue
        for condition in conditions:
            if re.search(r'hole|drill|annul', condition, re.I):
                raise ValueError('Geometry-dependent custom conditions require full DRC.')
        for node in rule:
            if not isinstance(node, list) or not node or node[0] != 'constraint':
                continue
            kind = node[1]
            if kind == 'assertion':
                raise ValueError('Custom assertions require full DRC.')
            if kind not in names:
                if re.search(r'hole|drill|annul|physical', kind, re.I):
                    raise ValueError('Unsupported physical constraint: ' + kind)
                continue
            if pad_only and kind in ('hole_size', 'annular_width'):
                continue
            target = bounds.setdefault(kind, {})
            for entry in node[2:]:
                if not isinstance(entry, list) or entry[0] not in ('min', 'max'):
                    continue
                if len(entry) != 2:
                    raise ValueError('Custom bound expression requires full DRC.')
                match = re.fullmatch(r'(\d+(?:\.\d*)?|\.\d+)(mm|mil|in)?', entry[1])
                if not match:
                    raise ValueError('Custom bound expression requires full DRC.')
                value = round(float(match[1]) * {'mm': 1e6, 'mil': 25400,
                                               'in': 25400000, None: 1e6}[match[2]])
                field = entry[0]
                if field == 'max' and kind not in ('hole_size', 'annular_width'):
                    raise ValueError('Maximum physical-clearance constraints require full DRC.')
                target[field] = (max(target.get(field, 0), value) if field == 'min' else
                                 min(target.get(field, value), value))
    return bounds
