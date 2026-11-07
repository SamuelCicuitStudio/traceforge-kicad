"""Live inventory, snapshot preparation and undoable via-manager commits."""
from __future__ import annotations

import json
import re
import secrets
import shutil
import tempfile
from pathlib import Path

import pcbnew

from .cancellation import check_payload
from .stitching_native import refill, transaction, uid
from .via_manager import digest, resize_text, size_catalog, via_blocks

_session = None


def _vias(board):
    return {uid(item): item for item in board.GetTracks() if isinstance(item, pcbnew.PCB_VIA)}


def _row(via):
    layers = list(via.GetLayerSet().CuStack())
    widths = [via.GetWidth(layer) for layer in layers]
    return dict(uuid=uid(via), net=str(via.GetNetname()),
                x_mm=via.GetPosition().x / 1e6, y_mm=via.GetPosition().y / 1e6,
                diameter_mm=max(widths) / 1e6, drill_mm=via.GetDrillValue() / 1e6,
                locked=via.IsLocked(), through=via.GetViaType() == pcbnew.VIATYPE_THROUGH,
                uniform=len(set(widths)) == 1,
                layers=f'{via.TopLayer()}:{via.BottomLayer()}')


def _filtered(board, payload):
    def matches(via):
        row = _row(via)
        if payload.get('selected_only') and not via.IsSelected():
            return False
        if 'net' in payload and row['net'] != payload['net']:
            return False
        for key in ('diameter_mm', 'drill_mm'):
            if payload.get(key) is not None and abs(row[key] - float(payload[key])) > 0.0000005:
                return False
        return True
    result = {}
    for identity, via in _vias(board).items():
        check_payload(payload)
        if matches(via):
            result[identity] = via
    return result


def _save(board, path):
    name = board.GetFileName()
    try:
        if not pcbnew.SaveBoard(str(path), board):
            raise RuntimeError('Could not snapshot the live PCB.')
    finally:
        board.SetFileName(name)
    return path.read_text(encoding='utf-8')


def _sidecars(source):
    return {suffix: digest(source.with_suffix(suffix))
            if source.with_suffix(suffix).is_file() else None
            for suffix in ('.kicad_pro', '.kicad_dru')}


def dispatch(board, operation, payload):
    global _session
    if operation == 'via_manage_inventory':
        rows = [_row(via) for via in _vias(board).values()]
        ds = board.GetDesignSettings()
        predefined = [(v.m_Diameter/1e6, v.m_Drill/1e6, 'project preset')
                      for v in ds.m_ViasDimensionsList]
        classes = list(ds.m_NetSettings.GetNetclasses().values())
        default = ds.m_NetSettings.GetDefaultNetclass()
        classes.append(default)
        predefined.extend(((nc.GetViaDiameter() if nc.GetViaDiameter() > 0 else
                            default.GetViaDiameter())/1e6,
                           (nc.GetViaDrill() if nc.GetViaDrill() > 0 else
                            default.GetViaDrill())/1e6,
                           'netclass: ' + str(nc.GetName())) for nc in classes)
        return dict(catalog_version=2, total=len(rows), sizes=size_catalog(rows, predefined),
                    nets=sorted({row['net'] for row in rows}))
    if operation in ('via_manage_select', 'via_manage_focus'):
        chosen = _filtered(board, payload) if operation == 'via_manage_select' else {
            identity: via for identity, via in _vias(board).items()
            if identity in set(payload.get('ids', []))}
        return dict(ids=list(chosen), count=len(chosen))
    if operation in ('via_manage_prepare', 'via_manage_prepare_delete'):
        check_payload(payload)
        if _session:
            _session['temp'].cleanup()
            _session = None
        source = Path(board.GetFileName())
        if not source.is_file() or not source.with_suffix('.kicad_pro').is_file():
            raise ValueError('Save the PCB and project before using Via Size Manager.')
        chosen = _filtered(board, payload)
        if not chosen:
            raise ValueError('No vias match the current filters.')
        temp = tempfile.TemporaryDirectory(prefix='traceforge-vias-')
        folder = Path(temp.name)
        try:
            snapshot = folder / source.name
            original = _save(board, snapshot)
            check_payload(payload)
            for suffix in ('.kicad_pro', '.kicad_dru'):
                sidecar = source.with_suffix(suffix)
                if sidecar.is_file():
                    shutil.copy2(sidecar, snapshot.with_suffix(suffix))
            custom = {match[1] for _, _, block in via_blocks(original)
                      if '(padstack' in block and
                      (match := re.search(r'\(uuid "([^"]+)"\)', block))}
            rows = []
            diameter = float(payload.get('target_diameter_mm', 0.6))
            drill = float(payload.get('target_drill_mm', 0.3))
            if not (0 < drill < diameter <= 10):
                raise ValueError('Target diameter must exceed its positive drill (max 10 mm).')
            for identity, via in chosen.items():
                check_payload(payload)
                row = _row(via)
                reason = ''
                if row['locked']:
                    reason = 'Locked via.'
                elif operation == 'via_manage_prepare_delete':
                    pass
                elif not row['through'] or not row['uniform'] or identity in custom:
                    reason = 'Automatic resize supports uniform, ordinary through vias only.'
                elif diameter < row['diameter_mm'] or drill < row['drill_mm']:
                    reason = 'Enlargement only; target would shrink this via.'
                elif (diameter, drill) == (row['diameter_mm'], row['drill_mm']):
                    reason = 'Already at target size.'
                row.update(status='skipped' if reason else 'candidate', reason=reason)
                rows.append(row)
            token = secrets.token_hex(16)
            _session = dict(temp=temp, board=str(source), original=original,
                            sidecars=_sidecars(source), token=token, rows=rows,
                            diameter=diameter, drill=drill, operation=operation)
            result = dict(token=token, snapshot=str(snapshot),
                        result_file=str(folder/'result.json'),
                        diameter_mm=diameter, drill_mm=drill, vias=rows,
                        board_total=len(_vias(board)),
                        board_below_target=sum(v.GetDrillValue() < round(drill*1e6)
                                               for v in _vias(board).values()))
            candidates = {row['uuid']: chosen[row['uuid']] for row in rows
                          if row['status'] == 'candidate'}
            if (operation == 'via_manage_prepare' and candidates and
                    all(_row(v)['diameter_mm'] == diameter for v in candidates.values())):
                from .via_drill_native import check_holes, limit_signature

                checks, fallback = check_holes(board, candidates, round(drill*1e6),
                                               cancel_file=payload.get('cancel_file'))
                if checks is not None:
                    result['hole_checks'] = checks
                    _session['drill_signature'] = limit_signature(board)
                else:
                    result['fallback_reason'] = fallback
            check_payload(payload)
            return result
        except Exception:
            temp.cleanup()
            _session = None
            raise
    if operation not in ('via_manage_apply', 'via_manage_delete'):
        raise ValueError('Unsupported via manager operation.')
    saved = _session
    if not saved or payload.get('token') != saved['token']:
        raise ValueError('Preview expired; scan again.')
    _session = None
    try:
        source = Path(board.GetFileName())
        if str(source) != saved['board'] or _sidecars(source) != saved['sidecars']:
            raise ValueError('The board, project or custom rules changed; scan again.')
        current = _save(board, Path(saved['temp'].name)/'current.kicad_pcb')
        if current != saved['original']:
            raise ValueError('The live PCB changed after preview; scan again.')
        if operation == 'via_manage_delete':
            if saved['operation'] != 'via_manage_prepare_delete':
                raise ValueError('Preview is not a deletion preview.')
            identities = {row['uuid'] for row in saved['rows'] if row['status'] == 'candidate'}
        else:
            if saved['operation'] != 'via_manage_prepare':
                raise ValueError('Preview is not a resize preview.')
            result_path = Path(saved['temp'].name) / 'result.json'
            result = json.loads(result_path.read_text(encoding='utf-8'))
            if result['token'] != saved['token']:
                raise ValueError('Resize analysis token mismatch.')
            if result.get('method') == 'local hole checks':
                from .via_drill_native import limit_signature

                if limit_signature(board) != saved.get('drill_signature'):
                    raise ValueError('Live drill constraints changed; analyze again.')
            identities = set(result['ready'])
            expected = resize_text(saved['original'], identities, saved['diameter'], saved['drill'])
            snapshot = Path(result['snapshot'])
            if (snapshot.read_text(encoding='utf-8') != expected or
                    digest(snapshot) != result['verified_sha256']):
                raise ValueError('Verified board snapshot changed; scan again.')
        if not identities:
            return dict(count=0, message='No eligible vias to change.')

        def apply(live):
            vias = _vias(live)
            for identity in identities:
                via = vias[identity]
                if via.IsLocked():
                    raise ValueError('A via was locked after preview.')
                if operation == 'via_manage_delete':
                    live.RemoveNative(via)
                else:
                    via.SetWidth(round(saved['diameter'] * 1e6))
                    via.SetDrill(round(saved['drill'] * 1e6))
            if operation == 'via_manage_apply' and result.get('method') == 'local hole checks':
                live.BuildConnectivity()  # Copper envelopes and zone clearances are unchanged.
            else:
                refill(live)
            pcbnew.Refresh()
            verb = 'Deleted' if operation == 'via_manage_delete' else 'Resized'
            return dict(count=len(identities),
                        message=f'{verb} {len(identities)} vias. '
                                'Undo restores them; save normally.')

        return transaction(board, apply)
    finally:
        saved['temp'].cleanup()
