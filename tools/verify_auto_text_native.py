"""In-memory KiCad checks; no user files, live editor or GUI Undo needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pcbnew as k  # noqa: E402

from signal_path_analyzer import stitching_native  # noqa: E402
from signal_path_analyzer import traceforge_auto_text as text  # noqa: E402


def fixture():
    board = k.BOARD()
    board.SetFileName('auto-text-fixture.kicad_pcb')
    net = k.NETINFO_ITEM(board, 'signal', 1)
    board.Add(net)
    fp = k.FOOTPRINT(board)
    fp.SetReference('U123')
    fp.SetValue('CTRL')
    fp.SetFPIDAsString('Fixture:IC')
    board.Add(fp)
    pad = k.PAD(fp)
    pad.SetNumber('1')
    pad.SetAttribute(k.PAD_ATTRIB_SMD)
    pad.SetSize(k.VECTOR2I(k.FromMM(3), k.FromMM(2)))
    layers = k.LSET()
    layers.AddLayer(k.F_Cu)
    pad.SetLayerSet(layers)
    fp.Add(pad)
    pad.SetNet(net)
    fp.SetPosition(k.VECTOR2I(k.FromMM(15), k.FromMM(15)))
    fp.Reference().SetPosition(fp.GetPosition())
    fp.Reference().SetLayer(k.F_Fab)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    for a, b in [((0, 0), (40, 0)), ((40, 0), (40, 40)),
                 ((40, 40), (0, 40)), ((0, 40), (0, 0))]:
        edge = k.PCB_SHAPE()
        edge.SetShape(k.SHAPE_T_SEGMENT)
        edge.SetLayer(k.Edge_Cuts)
        edge.SetStart(text._v(a))
        edge.SetEnd(text._v(b))
        board.Add(edge)
    return board, fp, pad


def main():
    original_transaction = stitching_native.transaction
    original_refresh = k.Refresh
    original_selection = k.GetCurrentSelection
    stitching_native.transaction = lambda board, job: job(board)
    k.Refresh = lambda: None
    try:
        for layer in ['F.SilkS', 'B.SilkS', 'F.Fab', 'Dwgs.User', 'User.1']:
            board, fp, pad = fixture()
            before = (fp.GetPosition().x, fp.GetPosition().y, fp.GetOrientationDegrees(),
                      pad.GetPosition().x, pad.GetPosition().y, pad.GetNetname(),
                      fp.m_Uuid.AsString(), pad.m_Uuid.AsString(), fp.Value().IsVisible())
            preview = text.native_dispatch(board, 'text_layout_preview', dict(
                scope='all', target_layer=layer, show_hidden_refs=True, standard_size=.8))
            assert preview['board_outline'], preview
            assert preview['counts']['move'] == 1, preview
            assert fp.Reference().GetLayer() == k.F_Fab
            assert not fp.Reference().IsVisible()  # Preview has no side effects
            result = text.native_dispatch(board, 'text_layout_apply', dict(token=preview['token']))
            assert result['moved'] == 1
            assert fp.Reference().GetLayer() == text._target_layer_id(layer)
            assert fp.Reference().IsVisible()
            assert fp.Reference().IsMirrored() == layer.startswith('B.')
            after = (fp.GetPosition().x, fp.GetPosition().y, fp.GetOrientationDegrees(),
                     pad.GetPosition().x, pad.GetPosition().y, pad.GetNetname(),
                     fp.m_Uuid.AsString(), pad.m_Uuid.AsString(), fp.Value().IsVisible())
            assert before == after
            try:
                text.native_dispatch(board, 'text_layout_apply', dict(token=preview['token']))
            except ValueError as exc:
                assert 'expired' in str(exc)
            else:
                raise AssertionError('Token was reusable')
        board, fp, pad = fixture()
        fp.SetLocked(True)
        try:
            text.native_dispatch(board, 'text_layout_preview', dict(scope='all'))
        except ValueError as exc:
            assert '1 locked footprints' in str(exc), str(exc)
        else:
            raise AssertionError('Locked component text was editable without opting in')
        origin = text._xy(fp.GetPosition())
        preview = text.native_dispatch(board, 'text_layout_preview', dict(
            scope='all', text_on_locked_footprints=True, show_hidden_refs=True,
            target_layer='F.SilkS'))
        text.native_dispatch(board, 'text_layout_apply', dict(token=preview['token']))
        assert fp.IsLocked() and text._xy(fp.GetPosition()) == origin
        fp.Reference().SetLocked(True)
        try:
            text.native_dispatch(board, 'text_layout_preview', dict(
                scope='all', text_on_locked_footprints=True))
        except ValueError as exc:
            assert 'locked text fields' in str(exc), str(exc)
        else:
            raise AssertionError('Individually locked text was editable')
        board, fp, pad = fixture()
        graphic = k.PCB_TEXT(fp)
        graphic.SetText('${REFERENCE}')
        graphic.SetLayer(k.F_Fab)
        graphic.SetPosition(fp.GetPosition())
        graphic.SetTextSize(k.VECTOR2I(k.FromMM(.8), k.FromMM(.8)))
        fp.Add(graphic)
        # Native reference is hidden: only the visible dynamic copy is eligible.
        preview = text.native_dispatch(board, 'text_layout_preview', dict(
            scope='all', target_layer='F.SilkS', standard_size=.8))
        assert len(preview['rows']) == 1, preview
        assert preview['rows'][0]['kind'] == 'Reference copy'
        assert graphic.GetLayer() == k.F_Fab
        origin = text._xy(fp.GetPosition())
        value = fp.Value().GetText()
        result = text.native_dispatch(board, 'text_layout_apply', dict(token=preview['token']))
        assert result['moved'] == 1
        assert graphic.GetLayer() == k.F_SilkS
        assert graphic.GetText() == '${REFERENCE}'
        assert fp.Value().GetText() == value and text._xy(fp.GetPosition()) == origin
        assert not fp.Reference().IsVisible()
        # Copies can be disabled and selected directly through their parent.
        k.GetCurrentSelection = lambda: [graphic]
        assert text._selection_ids(board, 'selected') == [text._uid(fp)]
        try:
            text.native_dispatch(board, 'text_layout_preview', dict(
                scope='all', include_reference_copies=False))
        except ValueError:
            pass
        else:
            raise AssertionError('Disabled reference copies were discovered')
        board, fp, _ = fixture()
        rules = board.GetDesignSettings()
        rules.m_MinSilkTextHeight = k.FromMM(1.2)
        rules.m_MinSilkTextThickness = k.FromMM(.2)
        preview = text.native_dispatch(board, 'text_layout_preview', dict(
            scope='all', target_layer='F.SilkS', show_hidden_refs=True,
            standard_size=.5, text_thickness=.05))
        assert preview['warnings']
        assert preview['rows'][0]['size'] == 1.2
        assert preview['rows'][0]['thickness'] == .2
        text.native_dispatch(board, 'text_layout_apply', dict(token=preview['token']))
        assert fp.Reference().GetTextThickness() == k.FromMM(.2)
        assert fp.Reference().GetTextSize().y == k.FromMM(1.2)
        board, fp, _ = fixture()
        k.GetCurrentSelection = lambda: [fp]
        assert text._selection_ids(board, 'selected') == [text._uid(fp)]
        group = k.PCB_GROUP(board)
        group.AddItem(fp)
        k.GetCurrentSelection = lambda: [group]
        assert text._selection_ids(board, 'selected') == [text._uid(fp)]
        preview = text.native_dispatch(board, 'text_layout_preview', dict(
            scope='all', target_layer='F.SilkS', show_hidden_refs=True))
        fp.SetPosition(text._v((16, 15)))
        try:
            text.native_dispatch(board, 'text_layout_apply', dict(token=preview['token']))
        except ValueError as exc:
            assert 'changed' in str(exc)
        else:
            raise AssertionError('Stale geometry was accepted')
    finally:
        stitching_native.transaction = original_transaction
        k.Refresh = original_refresh
        k.GetCurrentSelection = original_selection
    print('PASS: native layer/visibility/mirroring, reference-only edits, preview and stale guards')


if __name__ == '__main__':
    main()
