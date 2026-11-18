"""Audit real project asset preservation in temporary copies, never in board folders."""

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signal_path_analyzer import component_library as lib  # noqa: E402

base = Path(sys.argv[1])
report = []
for project_name, required in [
    (
        "01-MANAGEMENT-BOARD",
        [
            "TPS25940ARVCR",
            "TPS3702_Window",
            "R_0402",
            "C_0402",
            "L_Small",
            "FerriteBead_Small",
            "LED_Small",
        ],
    ),
    ("02-SIM-IO-BOARD", ["NANO_SIM_7P_H1.37", "LED_Small"]),
]:
    board = next((base / project_name).glob("*.kicad_pcb"))
    project = lib.discover(board)
    source = Path(project["symbol"]["path"])
    original = source.read_bytes()
    text = original.decode("utf-8-sig")
    definitions = {n.arg(): n for n in lib.parse(text).children("symbol")}
    if project_name == "01-MANAGEMENT-BOARD":
        multi = [n for n in definitions if "XC6" in n or "XC7" in n or "FPGA" in n]
        required += multi
    with tempfile.TemporaryDirectory(prefix="traceforge-project-audit-") as folder:
        root = Path(folder)
        sym_path = root / "Local.kicad_sym"
        shutil.copyfile(source, sym_path)
        fp_path = root / "Local.pretty"
        fp_path.mkdir()
        sym = dict(nickname="Local", path=str(sym_path))
        fp = dict(nickname="Local", path=str(fp_path))
        for name in required:
            assert name in definitions, name
            plan = lib.plan_import(
                root,
                dict(manufacturer="audit-fixture", mpn=name),
                sym,
                fp,
                reuse_symbol="Local:" + name,
            )
            lib.install(plan)
            assert sym_path.read_bytes() == original, name
            node = definitions[name]
            candidate = root / "candidate.kicad_sym"
            candidate.write_text(
                "(kicad_symbol_lib (version 20250114) "
                '(generator "test") ' + text[node.start : node.end] + ")",
                encoding="utf-8",
            )
            # Replacing an existing custom definition with different procurement
            # defaults is a conflict even when the drawing is superficially alike.
            try:
                lib.plan_import(
                    root,
                    dict(manufacturer="different-maker", mpn=name),
                    sym,
                    fp,
                    candidate_symbol=candidate,
                    reuse_footprint="",
                )
            except ValueError:
                pass
            else:
                raise AssertionError("Custom definition replacement was accepted: " + name)
            assert sym_path.read_bytes() == original
            report.append(dict(project=project_name, symbol=name, preserved=True))
    assert source.read_bytes() == original
    print(project_name, "source SHA256", hashlib.sha256(original).hexdigest())
for board, nickname, name in [
    ('01-MANAGEMENT-BOARD', 'RevC_Management', 'L_Coilcraft_XxL4020'),
    ('02-SIM-IO-BOARD', 'RevC_SIM_Capture', 'LED_LiteOn_LTST-S220KGKT_SideView'),
    ('02-SIM-IO-BOARD', 'RevC_SIM_Capture', 'SHOU_HAN_NANO_SIM_7P_H1.37_C7529384'),
]:
    source = base / board / 'libraries' / (nickname + '.pretty') / (name + '.kicad_mod')
    original = source.read_bytes()
    text = original.decode('utf-8-sig')
    node = lib.parse(text)
    for model in reversed(node.children('model')):
        text = text[:model.start] + text[model.end:]
    node = lib.parse(text)
    x = node.children('pad')[0].children('at')[0].value[1]
    text = text[:x.start] + str(float(x.value) + .123) + text[x.end:]
    with tempfile.TemporaryDirectory(prefix='traceforge-geometry-conflict-') as folder:
        root = Path(folder)
        library = root / 'Local.pretty'
        library.mkdir()
        target = library / source.name
        target.write_bytes(original)
        candidate = root / 'candidate.kicad_mod'
        candidate.write_text(text, encoding='utf-8')
        try:
            lib.plan_import(root, dict(manufacturer='audit', mpn=name),
                            dict(nickname='Local', path=str(root / 'Local.kicad_sym')),
                            dict(nickname='Local', path=str(library)),
                            candidate_footprint=candidate)
        except ValueError as exc:
            assert 'customized footprint preserved' in str(exc), str(exc)
        else:
            raise AssertionError('Same-name changed pad geometry was accepted: ' + name)
        assert target.read_bytes() == original
    assert source.read_bytes() == original
    report.append(dict(project=board, footprint=name, different_pads_rejected=True))
print(json.dumps(report, indent=2))
print("PASS: actual customized symbols and passive/SIM/LED definitions preserved")
