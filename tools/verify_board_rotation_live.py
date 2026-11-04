"""Exercise PCB Rotation and KiCad Undo in an isolated disposable PCB Editor."""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KICAD = Path(r'C:\Program Files\KiCad\10.0\bin')
sys.path.insert(0, str(ROOT))

from signal_path_analyzer.native_client import NativeBridge  # noqa: E402


def main():
    temp_root = Path(tempfile.mkdtemp(prefix='traceforge-rotation-live-')).resolve()
    if temp_root.parent != Path(tempfile.gettempdir()).resolve():
        raise RuntimeError('Disposable test directory is outside the system temp directory')
    editor = None
    try:
        config = temp_root / 'config'
        docs = temp_root / 'documents'
        local = temp_root / 'local'
        plugin_root = config / '10.0' / 'scripting' / 'plugins'
        plugin_root.mkdir(parents=True)
        source_config = Path(os.environ['APPDATA']) / 'kicad' / '10.0'
        for source_file in source_config.iterdir():
            if source_file.is_file():
                shutil.copy2(source_file, config / '10.0' / source_file.name)
        (docs / '10.0').mkdir(parents=True)
        local.mkdir()
        shutil.copytree(ROOT / 'native_bridge', plugin_root / 'traceforge_native_bridge',
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'signal_path_analyzer', plugin_root / 'signal_path_analyzer',
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'icons', plugin_root / 'icons')
        for name in ('traceforge_action.py', 'highlight_net_chain_action.py',
                     'signal_path_analyzer_action.py'):
            shutil.copy2(ROOT / name, plugin_root / name)

        server_file = plugin_root / 'traceforge_native_bridge' / 'server.py'
        source = server_file.read_text(encoding='utf-8')
        marker = "    if operation.startswith('teardrop_'):"
        test_ops = '''    if operation == 'rotate_test_select':
        for old in pcbnew.GetCurrentSelection():
            old.ClearSelected()
        kind = payload.get('kind', 'component')
        item = (next(fp for fp in board.GetFootprints() if fp.GetReference() == 'U1')
                if kind == 'component' else
                next(shape for shape in board.GetDrawings()
                     if isinstance(shape, pcbnew.PCB_SHAPE)
                     and shape.GetShape() == pcbnew.SHAPE_T_POLY)
                if kind == 'polygon' else next(iter(board.Zones())))
        item.SetSelected()
        pcbnew.Refresh()
        return True
    if operation == 'rotate_test_state':
        fp = next(fp for fp in board.GetFootprints() if fp.GetReference() == 'U1')
        polygon = next(shape for shape in board.GetDrawings()
                       if isinstance(shape, pcbnew.PCB_SHAPE)
                       and shape.GetShape() == pcbnew.SHAPE_T_POLY)
        zone = next(iter(board.Zones()), None)
        poly_point = polygon.GetPolyShape().CVertex(0)
        zone_point = zone.Outline().CVertex(0) if zone else None
        return {'angle': fp.GetOrientationDegrees(),
                'polygon': [poly_point.x, poly_point.y],
                'zone': [zone_point.x, zone_point.y] if zone_point else None,
                'selected': len(list(pcbnew.GetCurrentSelection()))}
    if operation == 'rotate_test_debug':
        import wx
        from signal_path_analyzer.stitching_native import editor_frame, COMMIT_LABEL, menu_item
        frame = editor_frame()
        return {'windows': [w.GetTitle() for w in wx.GetTopLevelWindows()
                            if isinstance(w, wx.Frame)],
                'frame': frame.GetTitle() if frame else None,
                'commit': bool(frame and any(menu_item(menu, COMMIT_LABEL)
                                              for menu, _ in frame.GetMenuBar().GetMenus())),
                'rotation_shortcut': bool(frame and any(menu_item(menu,
                    'TraceForge: PCB Rotation') for menu, _ in frame.GetMenuBar().GetMenus()))}
    if operation == 'rotate_test_undo_id':
        import wx
        from signal_path_analyzer.stitching_native import editor_frame, menu_item
        frame = editor_frame()
        item = next((found for menu, _ in frame.GetMenuBar().GetMenus()
                     if (found := menu_item(menu, wx.GetTranslation('Undo')))), None)
        if item is None:
            raise RuntimeError('KiCad Undo menu item was not found')
        return {'id': item.GetId(), 'enabled': item.IsEnabled(),
                'hwnd': int(frame.GetHandle()), 'label': item.GetItemLabelText()}
'''
        if source.count(marker) != 1:
            raise RuntimeError('Could not locate temporary test hook')
        server_file.write_text(source.replace(marker, test_ops + marker), encoding='utf-8')

        board_file = temp_root / 'rotation-test.kicad_pcb'
        make_board = '''import os
import pcbnew as p
import sys
b = p.BOARD()
f = p.FOOTPRINT(b)
f.SetReference('U1')
f.SetPosition(p.VECTOR2I(10000000, 10000000))
pad = p.PAD(f)
pad.SetPosition(p.VECTOR2I(12000000, 10000000))
f.Add(pad)
b.Add(f)
poly = p.PCB_SHAPE(b)
poly.SetShape(p.SHAPE_T_POLY)
poly.SetPolyPoints([p.VECTOR2I(x * 1000000, y * 1000000)
                    for x, y in ((20, 20), (24, 20), (24, 22), (20, 22))])
poly.SetLayer(p.Dwgs_User)
b.Add(poly)
edge = p.PCB_SHAPE(b)
edge.SetShape(p.SHAPE_T_RECT)
edge.SetStart(p.VECTOR2I(0, 0))
edge.SetEnd(p.VECTOR2I(50000000, 50000000))
edge.SetLayer(p.Edge_Cuts)
b.Add(edge)
if 'zone' in os.environ.get('TRACEFORGE_TEST_KINDS', ''):
    zone = p.ZONE(b)
    zone.SetLayer(p.F_Cu)
    zone.Outline().NewOutline()
    for x, y in ((30, 30), (34, 30), (34, 32), (30, 32)):
        zone.Outline().Append(p.VECTOR2I(x * 1000000, y * 1000000))
    b.Add(zone)
p.SaveBoard(sys.argv[1], b)
'''
        subprocess.run([str(KICAD / 'python.exe'), '-c', make_board, str(board_file)],
                       check=True, capture_output=True, text=True)

        env = dict(os.environ, KICAD_CONFIG_HOME=str(config), KICAD_DOCUMENTS_HOME=str(docs),
                   KICAD10_3RD_PARTY=str(docs / '10.0' / '3rdparty'),
                   APPDATA=str(config), LOCALAPPDATA=str(local))
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        editor = subprocess.Popen([str(KICAD / 'pcbnew.exe'), str(board_file)], env=env,
                                  startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        registry = local / 'TraceForge' / 'native-bridge' / f'{editor.pid}.json'
        deadline = time.monotonic() + 45
        while not registry.exists() and editor.poll() is None and time.monotonic() < deadline:
            time.sleep(0.25)
        if not registry.exists():
            raise RuntimeError(f'Isolated PCB Editor did not start its native bridge '
                               f'(exit={editor.poll()})')
        client = NativeBridge(str(board_file), json.loads(registry.read_text()))
        deadline = time.monotonic() + 60
        while True:
            try:
                info = client.call('info')
                break
            except RuntimeError as exc:
                if 'No saved board is open' not in str(exc) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        assert info['traceforge_version'] == '0.12.4', info
        editor_state = client.call('rotate_test_debug')
        print('Editor action state:', editor_state)
        assert editor_state['rotation_shortcut'], editor_state
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
        cases = {'component': 'angle', 'polygon': 'polygon', 'zone': 'zone'}
        selected_cases = os.environ.get('TRACEFORGE_TEST_KINDS', 'component')
        for kind in selected_cases.split(','):
            field = cases[kind]
            print('Selecting', kind, flush=True)
            assert client.call('rotate_test_select', kind=kind)
            print('Reading', kind, flush=True)
            before = client.call('rotate_test_state')
            assert before['selected'] == 1
            print('Rotating', kind, flush=True)
            result = client.call('rotate_apply', angle='45')
            assert result[{'component': 'components', 'polygon': 'shapes',
                           'zone': 'zones'}[kind]] == 1, result
            after = client.call('rotate_test_state')
            assert after[field] != before[field], (kind, before, after)
            undo = client.call('rotate_test_undo_id')
            assert undo['enabled'], undo
            user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
            time.sleep(0.5)
            restored = client.call('rotate_test_state')
            assert restored[field] == before[field], (kind, before, restored)
            print(f'LIVE PASS: {kind} rotated 45 degrees and KiCad Undo restored it')
    finally:
        if editor is not None and editor.poll() is None:
            editor.terminate()
            try:
                editor.wait(timeout=10)
            except subprocess.TimeoutExpired:
                editor.kill()
                editor.wait(timeout=10)
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == '__main__':
    main()
