"""Size inventory and conservative, batch DRC-tested via enlargement (no pcbnew)."""
from __future__ import annotations

import collections
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

PRESETS = ((0.45, 0.20), (0.50, 0.25), (0.60, 0.30), (0.70, 0.30), (0.80, 0.40))


def size_catalog(rows, predefined):
    """Merge used sizes with live project presets; keep unused presets visible."""
    groups = {}
    for diameter, drill, source in predefined:
        if not 0 < drill < diameter:
            continue
        key = (round(diameter * 1e6), round(drill * 1e6))
        group = groups.setdefault(key, dict(diameter_mm=key[0]/1e6, drill_mm=key[1]/1e6,
                                            count=0, locked=0, sources=[]))
        if source not in group['sources']:
            group['sources'].append(source)
    for row in rows:
        key = (round(row['diameter_mm']*1e6), round(row['drill_mm']*1e6))
        group = groups.setdefault(key, dict(diameter_mm=key[0]/1e6, drill_mm=key[1]/1e6,
                                            count=0, locked=0, sources=[]))
        group['count'] += 1
        group['locked'] += int(row['locked'])
    return [groups[key] for key in sorted(groups)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def via_blocks(text):
    """Return whole top-level via spans, respecting quoted parentheses."""
    for match in re.finditer(r'(?m)^\t\(via\s', text):
        start = match.start() + 1
        depth, quoted, escape = 0, False, False
        for end in range(start, len(text)):
            char = text[end]
            if quoted:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if not depth:
                    yield start, end + 1, text[start:end + 1]
                    break
        else:
            raise ValueError('Incomplete via in board snapshot.')


def resize_text(text, identities, diameter, drill):
    changes, found = [], set()
    for a, b, block in via_blocks(text):
        identity = re.search(r'\(uuid "([^"]+)"\)', block)
        if identity is None or identity[1] not in identities:
            continue
        if '(padstack' in block or re.search(r'^\(via\s+(?:blind|micro)', block):
            raise ValueError('Automatic resize supports uniform through vias only.')
        for key, value in (('size', diameter), ('drill', drill)):
            block, count = re.subn(r'\(' + key + r' [^()]+\)',
                                   f'({key} {value:.6f})', block, count=1)
            if count != 1:
                raise ValueError('Unsupported via geometry in snapshot.')
        changes.append((a, b, block))
        found.add(identity[1])
    if found != set(identities):
        raise ValueError('A candidate via disappeared from the board snapshot.')
    for a, b, block in reversed(changes):
        text = text[:a] + block + text[b:]
    return text


def finding_key(item):
    # Include the measured description: a worsened pre-existing error is new too.
    return (item['type'], item['severity'], item['description'],
            tuple(sorted(row.get('uuid', '') for row in item.get('items', []))))


def findings(report):
    if not isinstance(report.get('violations'), list):
        raise ValueError('KiCad did not produce a valid DRC report.')
    return (report['violations'] + report.get('unconnected_items', []) +
            report.get('schematic_parity', []))


def new_findings(baseline, proposed):
    previous = collections.Counter(finding_key(row) for row in baseline)
    result = []
    for row in proposed:
        key = finding_key(row)
        if previous[key]:
            previous[key] -= 1
        else:
            result.append(row)
    return result


def run_drc(cli, board, report, cancel=None):
    process = subprocess.Popen(
        [str(cli), 'pcb', 'drc', '--refill-zones', '--severity-all', '--format', 'json',
         '-o', str(report), str(board)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic()+300
    try:
        while True:
            if cancel:
                cancel.check()
            if time.monotonic() >= deadline:
                raise RuntimeError('KiCad DRC exceeded its five-minute limit.')
            try:
                stdout, stderr = process.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        process.kill()  # Only this temporary-board CLI child, never PCB Editor.
        process.communicate()
        raise
    if process.returncode != 0 or not report.is_file():
        raise RuntimeError('KiCad DRC failed: ' + (stderr or stdout)[-1500:])
    return findings(json.loads(report.read_text(encoding='utf-8')))


def analyze(prepared, cli=None, drc=run_drc, cancel=None):
    """Test all eligible growth together; remove implicated candidates and retest.

    The final batch must introduce no new findings. This deliberately sacrifices
    some possible changes rather than claiming an unsafe/global optimum.
    """
    path = Path(prepared['snapshot'])
    if cancel:
        cancel.check()
    original = path.read_text(encoding='utf-8')
    rows = [dict(row) for row in prepared['vias']]
    eligible = {row['uuid'] for row in rows if row['status'] == 'candidate'}
    if not eligible:
        return finish(prepared, original, rows, eligible, {}, None, 0, 'no changes')
    if prepared.get('hole_checks') is not None:
        checks = prepared['hole_checks']
        if set(checks) != eligible:
            raise ValueError('Incomplete drill-only checks; analyze again.')
        reasons = {key: value for key, value in checks.items() if value}
        eligible -= set(reasons)
        return finish(prepared, original, rows, eligible, reasons, None, 0, 'local hole checks')
    cli = Path(cli) if cli else Path('C:/Program Files/KiCad/10.0/bin/kicad-cli.exe')
    if drc is run_drc and not cli.is_file():
        raise FileNotFoundError('KiCad 10 kicad-cli is required for the resize DRC scan.')
    def scan(report):
        if cancel:
            cancel.check()
        value = (run_drc(cli,path,report,cancel=cancel) if drc is run_drc else
                 drc(cli,path,report))
        if cancel:
            cancel.check()
        return value

    baseline = scan(path.parent / 'baseline.json')
    reasons = {}
    passes = 0
    while eligible:
        passes += 1
        path.write_text(resize_text(original, eligible, prepared['diameter_mm'],
                                    prepared['drill_mm']), encoding='utf-8', newline='\n')
        proposed = scan(path.parent / f'candidate-{passes}.json')
        added = new_findings(baseline, proposed)
        if not added:
            break
        blocked = set()
        for issue in added:
            affected = {item.get('uuid') for item in issue.get('items', [])} & eligible
            if not affected:
                # Zone/aggregate findings need not carry the changed via's UUID.
                affected = set(eligible)
            blocked.update(affected)
            for identity in affected:
                reasons[identity] = issue['type'] + ': ' + issue['description']
        eligible -= blocked
        if passes >= 5 and eligible:
            for identity in eligible:
                reasons[identity] = 'Conservative batch limit reached; not verified.'
            eligible.clear()
    if cancel:
        cancel.check()
    return finish(prepared, original, rows, eligible, reasons, len(baseline), passes, 'full DRC')


def finish(prepared, original, rows, eligible, reasons, baseline, passes, method):
    path = Path(prepared['snapshot'])
    for row in rows:
        if row['status'] == 'candidate':
            row['status'] = 'ready' if row['uuid'] in eligible else 'blocked'
            row['reason'] = reasons.get(row['uuid'], 'Passed local drill checks.' if
                                       method == 'local hole checks' else
                                       'No new DRC findings in final batch.')
    # This exact file is verified again by the native apply operation.
    path.write_text(resize_text(original, eligible, prepared['diameter_mm'],
                                prepared['drill_mm']), encoding='utf-8', newline='\n')
    result = dict(prepared, vias=rows, ready=sorted(eligible),
                  baseline_findings=baseline, passes=passes, method=method,
                  verified_sha256=digest(path))
    result['board_remaining_small'] = prepared.get('board_below_target', 0) - sum(
        row['uuid'] in eligible and row['drill_mm'] < prepared['drill_mm'] for row in rows)
    Path(prepared['result_file']).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
