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
from signal_path_analyzer import __version__  # noqa: E402


def run_from_webview(client, info, scripts, tools=None):
    import wx
    from signal_path_analyzer.webview_ui import WebFrame, web

    app = wx.GetApp() or wx.App()
    frame = WebFrame(client.call, tools=tools, board_file=info["board"], native_info=info)
    reply = []
    send = frame.send

    def capture(result):
        reply.append(result)
        send(result)
        if result.get("error") or len(reply) == len(scripts):
            wx.CallAfter(frame.Close)
        elif scripts[len(reply)] is not None:
            wx.CallLater(100, frame.browser.RunScriptAsync, scripts[len(reply)])

    frame.send = capture
    def start(event):
        if event.GetURL() == frame.page_url:
            wx.CallLater(100, frame.browser.RunScriptAsync, scripts[0])
        event.Skip()

    frame.browser.Bind(web.EVT_WEBVIEW_LOADED, start)
    frame.Show()
    deadline = wx.CallLater(60000, app.ExitMainLoop)
    app.MainLoop()
    deadline.Stop()
    errors = [item["error"] for item in reply if item.get("error")]
    assert len(reply) == len(scripts) and not errors, (len(reply), len(scripts), errors)
    return reply


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
    if operation == 'clone_test_select':
        from .exact_selection import select_cloned_items
        refs = set(payload["refs"])
        ids = [fp.m_Uuid.AsString() for fp in board.GetFootprints() if fp.GetReference() in refs]
        return select_cloned_items(board, ids)[0]
    if operation == 'clone_test_state':
        return {'groups': len(list(board.Groups())),
                'positions': {fp.GetReference(): [fp.GetPosition().x, fp.GetPosition().y]
                              for fp in board.GetFootprints()},
                'tracks': sorted((track.GetNetname(), [track.GetStart().x, track.GetStart().y],
                                  [track.GetEnd().x, track.GetEnd().y]) for track in board.GetTracks())}
    if operation == 'text_test_state':
        ref = next(fp.Reference() for fp in board.GetFootprints() if fp.GetReference() == 'U1')
        return {'layer': ref.GetLayerName(), 'visible': ref.IsVisible(),
                'position': [ref.GetPosition().x, ref.GetPosition().y]}
    if operation == 'array_test_select':
        from .exact_selection import replace
        ids = [track.m_Uuid.AsString() for track in board.GetTracks()
               if isinstance(track, pcbnew.PCB_VIA) and track.GetNetname() == 'Array']
        return len(replace(board, ids))
    if operation == 'array_test_state':
        return {track.m_Uuid.AsString(): [track.GetNetname(), track.GetPosition().x,
                                         track.GetPosition().y, track.GetWidth(pcbnew.F_Cu),
                                         track.GetDrillValue()]
                for track in board.GetTracks() if isinstance(track, pcbnew.PCB_VIA)}
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
    if operation == 'teardrop_test_count':
        return sum(zone.IsTeardropArea() for zone in board.Zones())
    if operation == 'stitch_test_count':
        return sum(isinstance(item, pcbnew.PCB_VIA) for item in board.GetTracks())
'''
        if source.count(marker) != 1:
            raise RuntimeError('Could not locate temporary test hook')
        server_file.write_text(source.replace(marker, test_ops + marker), encoding='utf-8')

        board_file = temp_root / 'rotation-test.kicad_pcb'
        assignment_source = os.environ.get("TRACEFORGE_TEST_ASSIGNMENT_BOARD")
        make_board = '''import os
import pcbnew as p
import sys
b = p.BOARD()
b.SetCopperLayerCount(4)
f = p.FOOTPRINT(b)
f.SetReference('U1')
f.SetPosition(p.VECTOR2I(10000000, 10000000))
pad = p.PAD(f)
pad.SetPosition(p.VECTOR2I(12000000, 10000000))
f.Add(pad)
b.Add(f)
for ref, x, y in [('U2', 15, 10), ('U11', 30, 30), ('U12', 33, 35)]:
    other=p.FOOTPRINT(b)
    other.SetReference(ref)
    other.SetValue('A' if ref == 'U11' else 'B')
    other.SetPosition(p.VECTOR2I(x*1000000,y*1000000))
    child=p.PAD(other)
    child.SetPosition(other.GetPosition()+p.VECTOR2I(2000000,0))
    other.Add(child)
    b.Add(other)
f.SetValue('A')
f.Reference().SetLayer(p.F_Fab)
f.Reference().SetPosition(f.GetPosition())
f.Reference().SetVisible(False)
for group, refs in enumerate((('U1','U2'), ('U11','U12')), 1):
    net = p.NETINFO_ITEM(b, 'Grid'+str(group))
    b.Add(net)
    selected = {fp.GetReference():fp for fp in b.GetFootprints()}
    for index, ref in enumerate(refs, 1):
        fp = selected[ref]
        path = p.KIID_PATH()
        for number in (group, 100+index):
            path.push_back(p.KIID('00000000-0000-0000-0000-'+str(number).zfill(12)))
        fp.SetPath(path)
        fp.SetSheetfile('grid.kicad_sch')
        next(iter(fp.Pads())).SetNet(net)
    if group == 1:
        track = p.PCB_TRACK(b)
        track.SetLayer(p.In1_Cu)
        track.SetWidth(150000)
        track.SetStart(next(iter(selected[refs[0]].Pads())).GetPosition())
        track.SetEnd(next(iter(selected[refs[1]].Pads())).GetPosition())
        track.SetNet(net)
        b.Add(track)
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
for name, positions in (('Array', ((35,20),(37,20),(43,20),(35,24),(37,24),(43,24))),
                        ('Obstacle', ((39,20),))):
    net = p.NETINFO_ITEM(b, name)
    b.Add(net)
    for x,y in positions:
        via=p.PCB_VIA(b)
        via.SetPosition(p.VECTOR2I(x*1000000,y*1000000))
        via.SetWidth(600000)
        via.SetDrill(300000)
        via.SetLayerPair(p.F_Cu,p.B_Cu)
        via.SetNet(net)
        b.Add(via)
bga = p.FOOTPRINT(b)
bga.SetReference('UBGA')
bga.SetPosition(p.VECTOR2I(20000000,35000000))
b.Add(bga)
for y in range(4):
    for x in range(4):
        net = p.NETINFO_ITEM(b,f'BGA_{y}_{x}')
        b.Add(net)
        pad=p.PAD(bga)
        pad.SetNumber(f'{chr(65+y)}{x+1}')
        pad.SetAttribute(p.PAD_ATTRIB_SMD)
        pad.SetShape(p.PAD_SHAPE_CIRCLE)
        pad.SetSize(p.VECTOR2I(450000,450000))
        layers=p.LSET()
        layers.AddLayer(p.F_Cu)
        pad.SetLayerSet(layers)
        pad.SetPosition(bga.GetPosition()+p.VECTOR2I(x*1000000,y*1000000))
        bga.Add(pad)
        pad.SetNet(net)
cleanup_net = p.NETINFO_ITEM(b, 'Cleanup')
b.Add(cleanup_net)
for _ in range(2):
    track = p.PCB_TRACK(b)
    track.SetStart(p.VECTOR2I(5000000, 25000000))
    track.SetEnd(p.VECTOR2I(10000000, 25000000))
    track.SetWidth(200000)
    track.SetLayer(p.F_Cu)
    track.SetNet(cleanup_net)
    b.Add(track)
fillet_net = p.NETINFO_ITEM(b, 'Fillet')
b.Add(fillet_net)
for start, end in (((5, 40), (10, 40)), ((10, 40), (10, 45))):
    track = p.PCB_TRACK(b)
    track.SetStart(p.VECTOR2I(*(value*1000000 for value in start)))
    track.SetEnd(p.VECTOR2I(*(value*1000000 for value in end)))
    track.SetWidth(200000)
    track.SetLayer(p.F_Cu)
    track.SetNet(fillet_net)
    b.Add(track)
p.SaveBoard(sys.argv[1], b)
'''
        teardrop_only = os.environ.get('TRACEFORGE_TEST_KINDS') == 'teardrops'
        if teardrop_only:
            make_board += '''
pad = next(pad for pad in bga.Pads() if pad.GetNumber() == 'A1')
track = p.PCB_TRACK(b)
track.SetStart(pad.GetPosition())
track.SetEnd(pad.GetPosition() - p.VECTOR2I(3000000, 0))
track.SetWidth(120000)
track.SetLayer(p.F_Cu)
track.SetNet(pad.GetNet())
b.Add(track)
p.SaveBoard(sys.argv[1], b)
'''
        stitching_source = os.environ.get('TRACEFORGE_TEST_STITCHING_BOARD')
        if stitching_source:
            shutil.copy2(Path(stitching_source).resolve(strict=True), board_file)
        elif assignment_source:
            source_board = Path(assignment_source).resolve(strict=True)
            project = temp_root / "assignment"
            shutil.copytree(source_board.parent, project,
                            ignore=shutil.ignore_patterns("~*", "_autosave*", "review", "*.zip"))
            board_file = project / source_board.name
        else:
            subprocess.run([str(KICAD / 'python.exe'), '-c', make_board, str(board_file)],
                           check=True, capture_output=True, text=True)
            board_file.with_suffix(".kicad_pro").write_text("{}\n", encoding="utf-8")

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
        assert info['traceforge_version'] == __version__, info
        if assignment_source:
            from signal_path_analyzer import bom_source, component_schema
            from signal_path_analyzer.component_runtime import Worker

            schematic = board_file.with_suffix(".kicad_sch")
            cli = str(KICAD / "kicad-cli.exe")
            parts = bom_source.saved_schematic(schematic, Worker(), cli)["parts"]
            ref = "U800"
            expected = next(part for part in parts if part["reference"] == ref)
            calculated, research, catalog, assigned = run_from_webview(client, info, [
                "activate('manufacturing.cost');run('bom_calculate');",
                "const index=Array.from(el('bom-rows').rows).findIndex(row=>JSON.parse(row.dataset.references).includes('U800'));"
                "run('catalog_replacement',{row:index,replacement:false});",
                None,  # Entering replacement mode starts the catalog lookup.
                "const button=Array.from(el('catalog-rows').querySelectorAll('button')).find(button=>button.textContent==='TPS2553DBVR');"
                "button.click();window.confirm=()=>true;el('catalog-assign').click();",
            ])
            assert any("U800" in line["references"] for line in calculated["bom"]["lines"])
            assert "U800" in research["replacement"]["references"]
            assert any(part["code"] == "C55266" for part in catalog["catalog_page"]["parts"])
            assert assigned.get("replacement_closed") and "bom" in assigned, assigned
            after = bom_source.saved_schematic(schematic, Worker(), cli)["parts"]
            updated = next(part for part in after if part["reference"] == ref)
            observed = component_schema.properties(updated["properties"])
            assert observed["MPN"] == "TPS2553DBVR" and observed["LCSC Part #"] == "C55266"
            assert (updated["value"], updated["footprint"]) == (expected["value"], expected["footprint"])
            print("LIVE PASS: BOM research, assignment and incremental refresh through WebView and live PCB Editor")
            return
        editor_state = client.call('rotate_test_debug')
        print('Editor action state:', editor_state)
        assert editor_state['rotation_shortcut'], editor_state
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
        if stitching_source:
            initial = client.call('stitch_test_count')
            fence_net = os.environ.get('TRACEFORGE_TEST_FENCE_NET')
            load = ("activate('vias.fencing');"
                    f"el('signal-net').value={json.dumps(fence_net)};run('stitch_path');"
                    if fence_net else "activate('vias.stitching');run('stitch_load');")
            preview_script = ("el('stitch-settings').elements.trace_gap.value='1.2';"
                              "el('stitch-settings').elements.pitch_x.value='2';"
                              if fence_net else "") + "run('stitch_preview');"
            _, preview, applied = run_from_webview(client, info, [
                load,
                preview_script,
                "el('stitch-apply').click();",
            ])
            count = len(preview['stitch_preview']['accepted'])
            assert count and client.call('stitch_test_count') == initial + count
            assert any(group['count'] == count for group in applied['stitch_scene']['sets'])
            undo = client.call('rotate_test_undo_id')
            assert undo['enabled'], undo
            user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
            time.sleep(0.5)
            assert client.call('stitch_test_count') == initial
            tool = 'Via Fencing' if fence_net else 'Via Stitching'
            print(f'LIVE PASS: WebView {tool} preview, Apply of {count} vias and KiCad Undo')
            return
        if teardrop_only:
            assert client.call('teardrop_test_count') == 0
            run_from_webview(client, info, [
                "activate('routing.teardrops');run('teardrop_apply');",
            ])
            generated = client.call('teardrop_test_count')
            assert generated > 0
            run_from_webview(client, info, [
                "activate('routing.teardrops');"
                "el('teardrop-settings').elements.operation.value='remove';"
                "updateTeardropOptions();run('teardrop_apply');",
            ])
            assert client.call('teardrop_test_count') == 0
            undo = client.call('rotate_test_undo_id')
            assert undo['enabled'], undo
            user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
            time.sleep(0.5)
            assert client.call('teardrop_test_count') == generated
            undo = client.call('rotate_test_undo_id')
            assert undo['enabled'], undo
            user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
            time.sleep(0.5)
            assert client.call('teardrop_test_count') == 0
            print('LIVE PASS: WebView Teardrops Add, Remove and both KiCad Undo steps')
            return
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
            run_from_webview(client, info, ["activate('layout.rotate');run('rotate_apply');"])
            after = client.call('rotate_test_state')
            assert after[field] != before[field], (kind, before, after)
            undo = client.call('rotate_test_undo_id')
            assert undo['enabled'], undo
            user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
            time.sleep(0.5)
            restored = client.call('rotate_test_state')
            assert restored[field] == before[field], (kind, before, restored)
            print(f'LIVE PASS: {kind} rotated 45 degrees and KiCad Undo restored it')
        before = client.call('clone_test_state')
        assert client.call('clone_test_select', refs=['U1', 'U2']) == 2

        def clone_action(action, **payload):
            result = client.call(action, **payload)
            if action == 'layout_clone_capture':
                assert client.call('clone_test_select', refs=['U11', 'U12']) == 2
            return result

        run_from_webview(type('CloneClient', (), {'call': staticmethod(clone_action)})(), info, [
            "activate('layout.clone');el('mode').value='placement';run('record');",
            "el('anchor').value='U1';el('group_cloned').checked=true;run('apply');",
        ])
        cloned = client.call('clone_test_state')
        assert cloned['groups'] == 1
        assert cloned['positions']['U12'] == [35000000, 30000000], cloned
        undo = client.call('rotate_test_undo_id')
        assert undo['enabled'], undo
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('clone_test_state') == before
        print('LIVE PASS: WebView Layout Clone created a group and KiCad Undo restored placement')
        assert client.call('clone_test_select', refs=['U1', 'U2']) == 2
        run_from_webview(client, info, [
            "activate('layout.clone');el('scope').value='hierarchy';el('mode').value='both';run('record');",
            "window.confirm=()=>true;el('grid_x').value='15';run('grid');",
            "el('grid_x').value='25';run('grid');",
        ])
        recloned = client.call('clone_test_state')
        new_tracks = [track for track in recloned['tracks'] if track[0] in ('Grid1','Grid2')]
        source_track = next(track for track in before['tracks'] if track[0]=='Grid1')
        assert len(new_tracks) == 2 and new_tracks[1][0] == 'Grid2', recloned
        assert new_tracks[1][1][0] - source_track[1][0] == 25000000, recloned
        for pitch in (15000000, None):
            undo = client.call('rotate_test_undo_id')
            assert undo['enabled'], undo
            user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
            time.sleep(0.5)
            state = client.call('clone_test_state')
            if pitch is None:
                assert state == before, state
            else:
                target_track = next(track for track in state['tracks'] if track[0]=='Grid2')
                assert target_track[1][0] - source_track[1][0] == pitch, state
        print('LIVE PASS: WebView routed grid reclone replaced prior copper and both Undo steps restored it')
        state = client.call('text_test_state')
        assert state['layer'] == 'F.Fab' and not state['visible'], state
        assert client.call('clone_test_select', refs=['U1']) == 1
        run_from_webview(client, info, [
            "activate('layout.references');const form=el('text-settings').elements;"
            "form.target_layer.value='F.SilkS';form.show_hidden_refs.checked=true;run('text_layout_preview');",
            "el('text-apply').click();",
        ])
        edited = client.call('text_test_state')
        assert edited['layer'] == 'F.Silkscreen' and edited['visible'], edited
        undo = client.call('rotate_test_undo_id')
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('text_test_state') == state
        print('LIVE PASS: WebView Auto Text moved a hidden reference onto silkscreen and Undo restored it')
        array_before = client.call('array_test_state')
        assert client.call('array_test_select') == 6
        blocked, override, applied = run_from_webview(client, info, [
            "activate('vias.array');el('axis').value='columns';el('count').value='3';run('array_preview');",
            "el('ignore_drc').click();run('array_preview');",
            "el('apply-array').click();",
        ])
        assert not blocked['array']['accepted'] and override['array']['accepted'], (blocked, override)
        assert applied['array_applied'], applied
        array_after = client.call('array_test_state')
        assert set(array_before) == set(array_after)
        assert {row[1] for row in array_after.values() if row[0] == 'Array'} == {35000000,39000000,43000000}
        undo = client.call('rotate_test_undo_id')
        assert undo['enabled']
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('array_test_state') == array_before
        print('LIVE PASS: WebView Via Array blocked clearance, honored the override and Undo restored all vias')
        inventory, deletion, removed = run_from_webview(client, info, [
            "activate('vias.sizes');run('via_size_inventory');",
            "el('via-net').value='Array';run('via_size_review_delete');",
            "window.confirm=()=>true;el('via-delete').click();",
        ])
        assert deletion['delete_count'] == 6
        assert removed['via_inventory']['total'] == inventory['via_inventory']['total'] - 6
        assert all(row[0] != 'Array' for row in client.call('array_test_state').values())
        undo = client.call('rotate_test_undo_id')
        assert undo['enabled']
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('array_test_state') == array_before
        print('LIVE PASS: Via Size Manager deleted reviewed vias, refreshed inventory and preserved Undo')
        _, resize, resized = run_from_webview(client, info, [
            "activate('vias.sizes');run('via_size_inventory');",
            "el('via-net').value='Array';el('via-diameter').value='.7';el('via-drill').value='.35';run('via_size_preview');",
            "el('via-resize').click();",
        ])
        assert resize['resize_ready'] == 6, resize
        assert resized['via_inventory']['total'] == len(array_before)
        resized_vias = client.call('array_test_state')
        assert resized_vias == {key: row[:3]+[700000,350000] if row[0]=='Array' else row
                               for key,row in array_before.items()}, resized_vias
        undo = client.call('rotate_test_undo_id')
        assert undo['enabled']
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('array_test_state') == array_before
        print('LIVE PASS: Via Size Manager resized six reviewed vias and Undo restored their dimensions')
        assert client.call('clone_test_select', refs=['UBGA']) == 1
        _, preview, applied = run_from_webview(client, info, [
            "activate('routing.fanout');run('fanout_analyze');",
            "window.confirm=()=>true;const form=el('fanout-settings').elements;"
            "form.preset.value='custom';form.diameter.value='.5';form.drill.value='.3';"
            "form.width.value='.2';form.clearance.value='.2';form.netclass_width.checked=false;"
            "run('fanout_preview');",
            "el('fanout-apply').click();",
        ])
        accepted = preview['fanout_preview']['accepted']
        assert len(accepted) == 16, preview['fanout_preview']['reasons']
        assert applied['fanout']['managed_items'] == 32, applied['message']
        assert len(client.call('array_test_state')) == len(array_before) + 16
        undo = client.call('rotate_test_undo_id')
        assert undo['enabled']
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('array_test_state') == array_before
        print('LIVE PASS: WebView BGA Fanout previewed 16 breakouts, applied vias and tracks, and Undo restored the board')
        gaps, focused, cleared = run_from_webview(client, info, [
            "activate('signals.unrouted');run('gaps_scan');",
            "el('gap-filter').value='Grid2';drawGaps();el('gap-next').click();",
            "run('gaps_clear');",
        ])
        gap = next(row for row in gaps['gaps'] if row['net'] == 'Grid2')
        assert focused == {'focused_gap': gap['id'], 'message': 'Zoomed to gap.'}, focused
        assert cleared['focused_gap'] is None
        print('LIVE PASS: WebView Unrouted located Grid2, zoomed to the gap and cleared the highlight')
        from signal_path_analyzer.chains import ChainDef, Config, GroupDef
        from signal_path_analyzer.profiles import ProjectTiming
        from signal_path_analyzer.session import Session
        from traceforge_action import build_tools

        config = Config([
            GroupDef(name, (ChainDef(name, name, (net,)),))
            for name, net in (("Source", "Grid1"), ("Target", "Grid2"))
        ])
        session = Session(board_file.parent, board_file, ProjectTiming(), {}, config, None, client)
        scan, highlighted, _ = run_from_webview(client, info, [
            "activate('signals.paths');run('signals_refresh');",
            "for(const input of el('signal-rows').querySelectorAll('input'))input.click();"
            "el('signal-focus-groups').click();",
            "run('signals_clear');",
        ], tools=build_tools(session))
        assert {row['group'] for row in scan['signals']} == {'Source', 'Target'}
        assert highlighted['message'].endswith('across 2 groups.'), highlighted
        assert int(highlighted['message'].split()[1]) > 0, highlighted
        print('LIVE PASS: WebView Signals evaluated and highlighted two groups together')
        before_cleanup = client.call('clone_test_state')
        scanned, cleaned = run_from_webview(client, info, [
            "activate('routing.cleanup');el('cleanup-net').value='Cleanup';run('cleanup_scan');",
            "window.confirm=()=>true;el('cleanup-apply').click();",
        ])
        assert len(scanned['cleanup']['redundant']) == 1
        assert cleaned['cleanup_applied'], cleaned
        assert sum(row[0] == 'Cleanup' for row in client.call('clone_test_state')['tracks']) == 1
        undo = client.call('rotate_test_undo_id')
        assert undo['enabled']
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('clone_test_state') == before_cleanup
        print('LIVE PASS: Trace Cleanup removed the reviewed duplicate and Undo restored it')
        before_fillet = client.call('clone_test_state')
        reviewed, applied = run_from_webview(client, info, [
            "activate('routing.corners');el('fillet-scope').value='all';el('fillet-net').value='Fillet';run('fillet_preview');",
            "el('fillet-apply').click();",
        ])
        assert reviewed['fillet']['accepted'] == 1
        assert applied['message'] == 'Rounded 1 corners.'
        assert sum(row[0] == 'Fillet' for row in client.call('clone_test_state')['tracks']) == 3
        undo = client.call('rotate_test_undo_id')
        assert undo['enabled']
        user32.SendMessageW(undo['hwnd'], 0x111, undo['id'], 0)
        time.sleep(0.5)
        assert client.call('clone_test_state') == before_fillet
        print('LIVE PASS: Trace Fillets rounded a reviewed corner and Undo restored both original traces')
        _, _, restored = run_from_webview(client, info, [
            "activate('routing.corners');el('fillet-scope').value='all';el('fillet-net').value='Fillet';run('fillet_preview');",
            "el('fillet-apply').click();",
            "window.confirm=()=>true;run('fillet_restore');",
        ])
        assert restored['message'] == 'Restored 1 corners.', restored
        assert client.call('clone_test_state') == before_fillet
        print('LIVE PASS: Trace Fillets restored the original corner through the WebView restore action')
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
