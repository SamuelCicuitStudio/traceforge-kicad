"""Headless native placement checks. Run with KiCad's bundled Python.

Creates only an in-memory fixture; never loads or saves a user board. The
transaction wrapper is replaced for this check; GUI Undo still needs an editor check.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pcbnew  # noqa: E402

from signal_path_analyzer import stitching_native  # noqa: E402
from signal_path_analyzer import traceforge_layout_clone as clone  # noqa: E402


def main():
    board = pcbnew.BOARD()
    board.SetFileName('layout-clone-fixture.kicad_pcb')
    nets = {}
    for i, name in enumerate(['GND', 'VCC', 'a', 'b', 'c', 'd'], 1):
        net = pcbnew.NETINFO_ITEM(board, name, i)
        board.Add(net)
        nets[name] = net

    def add(ref, package, value, names, x, y, rotation):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetFPIDAsString('Fixture:' + package)
        for i, name in enumerate(names):
            pad = pcbnew.PAD(fp)
            pad.SetNumber(str(i + 1))
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetShape(pcbnew.PAD_SHAPE_RECT)
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1), pcbnew.FromMM(.8)))
            pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(i * 2), 0))
            layers = pcbnew.LSET()
            layers.AddLayer(pcbnew.F_Cu)
            pad.SetLayerSet(layers)
            fp.Add(pad)
            pad.SetNet(nets[name])
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        fp.SetOrientationDegrees(rotation)
        return fp

    source = [add('U1', 'IC', 'CTRL', ['VCC', 'a', 'GND'], 10, 10, 90),
              add('R1', 'R0603', '1k', ['a', 'b'], 15, 10, 180),
              add('C1', 'C0603', '100n', ['b', 'GND'], 20, 12, 270)]
    target = [add('U91', 'IC', 'CTRL', ['VCC', 'c', 'GND'], 100, 50, 0),
              add('R73', 'R0603', '1k', ['c', 'd'], 80, 70, 90),
              add('C22', 'C0603', '100n', ['d', 'GND'], 80, 60, 180)]
    template = clone._snapshot(board, source)
    expected = clone._snapshot(board, target)
    plan = clone.make_plan(template, expected)
    assert plan['can_apply'], plan['issues']
    before_ids = {fp.GetReference(): fp.m_Uuid.AsString() for fp in board.GetFootprints()}
    original_transaction = stitching_native.transaction
    original_refresh = pcbnew.Refresh
    stitching_native.transaction = lambda board, job: job(board)
    pcbnew.Refresh = lambda: None
    try:
        result = clone._apply_to_board(board, dict(template=template, expected_target=expected))
        assert result['moved'] == 3
        assert clone._snapshot(board, source) == template
        actual = clone._snapshot(board, target)
        for desired in plan['pairs']:
            item = next(x for x in actual['items'] if x['id'] == desired['target_id'])
            assert (item['x'], item['y'], item['angle']) == (
                desired['x'], desired['y'], desired['angle'])
        assert before_ids == {
            fp.GetReference(): fp.m_Uuid.AsString() for fp in board.GetFootprints()}
        try:
            clone._apply_to_board(board, dict(template=template, expected_target=expected))
        except ValueError as exc:
            assert 'changed' in str(exc)
        else:
            raise AssertionError('Stale placement was accepted')
        def copper(pad):
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pad.GetPosition())
            track.SetEnd(pad.GetPosition() + pcbnew.VECTOR2I(pcbnew.FromMM(2), 0))
            track.SetWidth(pcbnew.FromMM(.2))
            track.SetLayer(pcbnew.F_Cu)
            track.SetNet(pad.GetNet())
            board.Add(track)
            return track

        local = copper(next(pad for pad in target[1].Pads() if pad.GetNetname() == 'c'))
        shared = copper(next(pad for pad in target[0].Pads() if pad.GetNetname() == 'VCC'))
        local_id, shared_id = (item.m_Uuid.AsString() for item in (local, shared))
        local.SetLocked(True)
        try:
            clone._apply_to_board(board, dict(template=template, expected_target=actual))
        except ValueError as exc:
            assert 'locked' in str(exc)
        else:
            raise AssertionError('Locked local routing was accepted')
        local.SetLocked(False)
        clone._apply_to_board(board, dict(template=template, expected_target=actual))
        remaining = {item.m_Uuid.AsString() for item in board.GetTracks()}
        assert local_id not in remaining and shared_id in remaining
    finally:
        stitching_native.transaction = original_transaction
        pcbnew.Refresh = original_refresh
    print('PASS: native pad geometry/nets/UUIDs; source preservation; stale/routed guards')


def verify_routing_assets():
    import wx
    app = wx.App.Get() or wx.App(False)
    assert app
    board = pcbnew.BOARD()
    board.SetFileName('routing-clone-fixture.kicad_pcb')
    nets = {}
    for name in ('SRC', 'DST', 'GND', 'ORPHAN'):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net

    def component(ref, x, net):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetValue('TEST')
        fp.SetFPIDAsString('Fixture:TEST')
        for number, name in [('1', net), ('2', 'GND')]:
            pad = pcbnew.PAD(fp)
            pad.SetNumber(number)
            pad.SetSize(pcbnew.VECTOR2I(1000000, 1000000))
            pad.SetPosition(pcbnew.VECTOR2I((int(number)-1)*2000000, 0))
            fp.Add(pad)
            pad.SetNet(nets[name])
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(x*1000000, 10000000))
        return fp
    source = component('U1', 10, 'SRC')
    target = component('U2', 50, 'DST')
    track = pcbnew.PCB_TRACK(board)
    track.SetStart(pcbnew.VECTOR2I(10000000, 10000000))
    track.SetEnd(pcbnew.VECTOR2I(10000000, 15000000))
    track.SetWidth(200000)
    track.SetLayer(pcbnew.F_Cu)
    track.SetNet(nets['SRC'])
    board.Add(track)
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(track.GetEnd())
    via.SetWidth(600000)
    via.SetDrill(300000)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNet(nets['SRC'])
    board.Add(via)
    arc = pcbnew.PCB_ARC(board)
    arc.SetStart(pcbnew.VECTOR2I(10000000, 15000000))
    arc.SetMid(pcbnew.VECTOR2I(11000000, 16000000))
    arc.SetEnd(pcbnew.VECTOR2I(12000000, 15000000))
    arc.SetWidth(200000)
    arc.SetLayer(pcbnew.B_Cu)
    arc.SetNet(nets['SRC'])
    board.Add(arc)
    graphic = pcbnew.PCB_TEXT(board)
    graphic.SetText('Circuit label')
    graphic.SetLayer(pcbnew.F_SilkS)
    graphic.SetPosition(pcbnew.VECTOR2I(10000000, 7000000))
    board.Add(graphic)
    zone = pcbnew.ZONE(board)
    zone.SetLayer(pcbnew.F_Cu)
    zone.SetNet(nets['SRC'])
    zone.Outline().NewOutline()
    for x, y in [(10, 18), (14, 18), (14, 22), (10, 22)]:
        zone.Outline().Append(x*1000000, y*1000000)
    board.Add(zone)
    from signal_path_analyzer import layout_clone_assets as assets
    template = clone._snapshot(board, [source])
    original_constructor = pcbnew.BOARD
    original_factory = pcbnew.CreateEmptyBoard

    def reject_nested_board_constructor(*_args, **_kwargs):
        raise AssertionError('Use CreateEmptyBoard directly; embedded BOARD() is double-wrapped')

    pcbnew.BOARD = reject_nested_board_constructor
    pcbnew.CreateEmptyBoard = lambda: None  # Actual embedded failure reported by the user.
    try:
        template['assets'] = assets.capture(board, [source, track, via, arc, graphic, zone])
        old_selection = pcbnew.GetCurrentSelection
        pcbnew.GetCurrentSelection = lambda: [source, track, via, arc, graphic, zone]
        try:
            placement_capture = clone.dispatch(
                board, 'layout_clone_capture', dict(mode='placement'))
            assert placement_capture['assets']['counts'] == {}
            routed_capture = clone.dispatch(board, 'layout_clone_capture', dict(
                mode='both', include_graphics=True))
            assert routed_capture['assets']['counts'] == template['assets']['counts']
        finally:
            pcbnew.GetCurrentSelection = old_selection
    finally:
        pcbnew.BOARD = original_constructor
        pcbnew.CreateEmptyBoard = original_factory
    assert template['assets']['counts'] == dict(tracks=1, vias=1, arcs=1, graphics=1, zones=1)
    assert len(template['assets']['preview']) == 5
    assert any(p['kind'] == 'via' for p in template['assets']['preview'])
    assert any(p['kind'] == 'copper' and len(p['points']) > 2
               for p in template['assets']['preview'])
    assert assets.preview_from_native(template['assets']['native_board'])

    expected = clone._snapshot(board, [target])
    source_ids = {x.m_Uuid.AsString() for x in board.GetTracks()}
    source_graphic = graphic.GetPosition()
    transaction, refresh = stitching_native.transaction, pcbnew.Refresh
    stitching_native.transaction = lambda board, job: job(board)
    pcbnew.Refresh = lambda: None
    try:
        result = clone._apply_to_board(board, dict(
            template=template, expected_target=expected, mode='routing', include_graphics=True))
        assert result['moved'] == 0 and result['cloned_assets'] == 5, result
        assert clone._snapshot(board, [target]) == expected
        new_copper = [x for x in board.GetTracks() if x.m_Uuid.AsString() not in source_ids]
        assert len(new_copper) == 3
        assert all(x.GetNetname() == 'DST' for x in new_copper)
        assert len({x.m_Uuid.AsString() for x in board.GetTracks()}) == 6
        assert graphic.GetPosition() == source_graphic
        new_graphic = next(x for x in board.GetDrawings() if x != graphic)
        assert new_graphic.GetPosition().x == graphic.GetPosition().x + 40000000
        assert new_graphic.GetText() == graphic.GetText()
        new_zone = next(z for z in board.Zones() if z.m_Uuid != zone.m_Uuid)
        assert new_zone.GetNetname() == 'DST'
        assert new_zone.GetBoundingBox().GetLeft() == zone.GetBoundingBox().GetLeft()+40000000
        assert not new_zone.IsFilled()
        target2 = component('U3', 80, 'DST')
        target2.SetPosition(pcbnew.VECTOR2I(80000000, 60000000))
        target2.SetOrientationDegrees(90)
        expected2 = clone._snapshot(board, [target2])
        result2 = clone._apply_to_board(board, dict(
            template=template, expected_target=expected2, mode='both', include_graphics=True,
            group_cloned=True))
        assert result2['moved'] == 1 and result2['cloned_assets'] == 5
        assert result2['groups_created'] == 1
        group = next(iter(board.Groups()))
        assert len(group.GetItems()) == 6
        parent = pcbnew.Cast_to_PCB_GROUP(pcbnew.Cast_to_BOARD_ITEM(target2.GetParentGroup().AsEdaItem()))
        assert parent.m_Uuid.AsString() == group.m_Uuid.AsString()
        assert result2['selection_ids'] == [group.m_Uuid.AsString()]
        assert target2.GetOrientationDegrees() == 90
        assert target2.GetPosition() == pcbnew.VECTOR2I(80000000, 60000000)
        rotated_only = component('U6', 200, 'DST')
        rotated_only.SetOrientationDegrees(90)
        rotated_snapshot = clone._snapshot(board, [rotated_only])
        rotated_result = clone._apply_to_board(board, dict(
            template=template, expected_target=rotated_snapshot, mode='routing'))
        assert rotated_result['moved'] == 0
        assert rotated_result['cloned_assets'] == 4
        assert clone._snapshot(board, [rotated_only]) == rotated_snapshot
        # A real foreign-net collision must reject BEFORE any live placement changes.
        blocked = component('U5', 150, 'DST')
        blocked.SetOrientationDegrees(90)
        blocked_snapshot = clone._snapshot(board, [blocked])
        blocked_plan = clone.make_plan(template, blocked_snapshot)
        candidates = assets.prepare(board, template, blocked_snapshot, blocked_plan, 'both', False)
        obstacle = next(x for x in candidates if isinstance(x, pcbnew.PCB_TRACK))
        obstacle.SetNet(nets['ORPHAN'])
        board.Add(obstacle)
        try:
            clone._apply_to_board(board, dict(
                template=template, expected_target=blocked_snapshot, mode='both'))
        except ValueError as exc:
            assert 'Board unchanged' in str(exc), str(exc)
        else:
            raise AssertionError('Foreign copper collision was accepted')
        assert clone._snapshot(board, [blocked]) == blocked_snapshot
        board.Remove(obstacle)
        target3 = component('U4', 110, 'DST')
        expected3 = clone._snapshot(board, [target3])
        result3 = clone._apply_to_board(board, dict(
            template=template, expected_target=expected3, mode='placement'))
        assert result3['moved'] == 1 and result3['cloned_assets'] == 0
        bad = dict(template)
        orphan = pcbnew.PCB_TRACK(board)
        orphan.SetStart(track.GetStart())
        orphan.SetEnd(track.GetEnd())
        orphan.SetNet(nets['ORPHAN'])
        bad['assets'] = assets.capture(board, [orphan])
        bad_plan = clone.make_plan(bad, expected3)
        try:
            assets.prepare(board, bad, expected3, bad_plan, 'routing', False)
        except ValueError as exc:
            assert 'Cannot resolve' in str(exc), str(exc)
        else:
            raise AssertionError('An unmapped routing net was accepted')
        plan = clone.make_plan(template, expected)
        try:
            assets.prepare(board, template, expected, plan, 'routing', True)
        except ValueError as exc:
            assert 'identical' in str(exc), str(exc)
        else:
            raise AssertionError('An identical existing asset was not detected')
        try:
            clone._apply_to_board(board, dict(
                template=template, expected_target=expected, mode='routing'))
        except ValueError as exc:
            assert 'identical' in str(exc)
        else:
            raise AssertionError('Repeated routing duplicated existing target copper')
    finally:
        stitching_native.transaction, pcbnew.Refresh = transaction, refresh
    print('PASS: None-factory regression, native routing/graphics, '
          'remapped nets and routing-only placement')


if __name__ == '__main__':
    main()
    verify_routing_assets()
