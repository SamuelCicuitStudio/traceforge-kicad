"""In-memory native library-update checks; no user boards or live editor edits."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pcbnew as k  # noqa: E402

from signal_path_analyzer import component_update_native as update  # noqa: E402

SOURCE = """(footprint "R" (version 20241229) (generator "test") (layer "F.Cu")
 (property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS")
 (effects (font (size 1 1) (thickness 0.15))))
 (property "Value" "R" (at 0 2 0) (layer "F.Fab")
 (effects (font (size 1 1) (thickness 0.15))))
 (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
 (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")))"""

with tempfile.TemporaryDirectory(prefix="traceforge-update-native-") as folder:
    root = Path(folder)
    library = root / "Local.pretty"
    library.mkdir()
    asset = library / "R.kicad_mod"
    (root / "fp-lib-table").write_text(
        '(fp_lib_table (version 7) (lib (name "Local") (type "KiCad") '
        '(uri "${KIPRJMOD}/Local.pretty") (options "") (descr "")))'
    )
    for bottom, angle in [(False, 0), (False, 90), (True, 180), (True, 270)]:
        asset.write_text(SOURCE)
        board = k.BOARD()
        board.SetFileName(str(root / "fixture.kicad_pcb"))
        fp = k.FootprintLoad(str(library), "R")
        board.Add(fp)
        fp.SetFPIDAsString("Local:R")
        fp.SetReference("R123")
        fp.SetValue("10k")
        fp.SetField("MPN", "KEEP-MY-MPN")
        model = k.FP_3DMODEL()
        model.m_Filename = "${KIPRJMOD}/3dmodels/kept.step"
        fp.Models().push_back(model)
        group = k.PCB_GROUP(board)
        group.SetName("KEEP-GROUP")
        board.Add(group)
        group.AddItem(fp)
        fp.SetPosition(k.VECTOR2I(k.FromMM(20), k.FromMM(20)))
        if bottom:
            fp.Flip(fp.GetPosition(), False)
        fp.SetOrientationDegrees(angle)
        fp.Reference().SetVisible(False)
        fp.Reference().SetPosition(k.VECTOR2I(k.FromMM(18), k.FromMM(16)))
        net = k.NETINFO_ITEM(board, "NET", 1)
        board.Add(net)
        for pad in fp.Pads():
            pad.SetNet(net)
        pad = next(iter(fp.Pads()))
        track = k.PCB_TRACK(board)
        track.SetLayer(k.B_Cu if bottom else k.F_Cu)
        track.SetWidth(k.FromMM(0.2))
        track.SetNet(net)
        track.SetStart(pad.GetPosition())
        track.SetEnd(pad.GetPosition() + k.VECTOR2I(k.FromMM(5), 0))
        board.Add(track)
        board.BuildConnectivity()
        selection = [fp]
        k.GetCurrentSelection = lambda selection=selection: selection
        k.Refresh = lambda: None
        update.transaction = lambda live, action: action(live)
        state = update._state(board, fp)
        route = (track.GetStart().x, track.GetStart().y, track.GetEnd().x, track.GetEnd().y)
        result = update.dispatch(board, "component_update_preview", {}, lambda: "revision")
        assert result["ready"], result
        assert result["rows"][0]["checked_contacts"] > 0
        assert update._state(board, fp) == state  # Preview is read-only.
        applied = update.dispatch(
            board, "component_update_apply", dict(token=result["token"]), lambda: "revision"
        )
        assert applied["updated"] == ["R123"]
        current = board.FindFootprintByReference("R123")
        assert current.m_Uuid.AsString() == state["id"]
        assert current.GetValue() == "10k" and current.GetFieldText("MPN") == "KEEP-MY-MPN"
        assert current.GetLayer() == fp.GetLayer()
        assert current.GetOrientationDegrees() % 360 == angle % 360
        assert current.GetPosition() == fp.GetPosition()
        assert not current.Reference().IsVisible()
        assert current.Reference().GetPosition() == fp.Reference().GetPosition()
        assert all(p.GetNetname() == "NET" for p in current.Pads())
        assert list(current.Models())[0].m_Filename == "${KIPRJMOD}/3dmodels/kept.step"
        assert (
            k.Cast_to_PCB_GROUP(
                k.Cast_to_BOARD_ITEM(current.GetParentGroup().AsEdaItem())
            ).m_Uuid.AsString()
            == group.m_Uuid.AsString()
        )
        expected_pads = {p["number"]: p["local"] for p in state["pads"]}
        assert {
            p["number"]: p["local"] for p in update._state(board, current)["pads"]
        } == expected_pads
        assert route == (track.GetStart().x, track.GetStart().y, track.GetEnd().x, track.GetEnd().y)
        selection[:] = [current]
        preview = update.dispatch(board, "component_update_preview", {}, lambda: "revision")
        current.SetPosition(current.GetPosition() + k.VECTOR2I(1, 0))
        try:
            update.dispatch(
                board, "component_update_apply", dict(token=preview["token"]), lambda: "revision"
            )
        except ValueError as exc:
            assert "changed since preview" in str(exc)
        else:
            raise AssertionError("Stale placement was accepted")
        current.SetPosition(fp.GetPosition())
        asset.write_text(SOURCE.replace("(at -1 0)", "(at -20 0)"))
        blocked = update.dispatch(board, "component_update_preview", {}, lambda: "revision")
        assert not blocked["ready"], blocked
        assert "routed copper contact" in blocked["rows"][0]["reason"]
        asset.write_text(SOURCE)
        current.SetLocked(True)
        blocked = update.dispatch(board, "component_update_preview", {}, lambda: "revision")
        assert not blocked["ready"] and "Locked" in blocked["rows"][0]["reason"]
        current.SetLocked(False)
        model_preview = update.dispatch(
            board, "component_update_preview", dict(library_models=True), lambda: "revision"
        )
        assert model_preview["rows"][0]["old"]["models"]
        assert not model_preview["rows"][0]["new"]["models"]
        preview = update.dispatch(board, "component_update_preview", {}, lambda: "revision")
        asset.write_text(SOURCE + "\n")
        try:
            update.dispatch(
                board, "component_update_apply", dict(token=preview["token"]), lambda: "revision"
            )
        except ValueError as exc:
            assert "Library changed" in str(exc)
        else:
            raise AssertionError("Changed library was accepted")
    print(
        "PASS: native selected updates, rotated/bottom placement, UUID/net/fields/text/route "
        "preservation and stale guard"
    )
