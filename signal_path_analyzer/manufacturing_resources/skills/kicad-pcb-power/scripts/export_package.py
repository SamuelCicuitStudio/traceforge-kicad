"""Build a PCB Power manufacturing package from a saved KiCad 10 project.

Read-only on the design: every output comes from `kicad-cli`, then it is packaged and checked.

    python export_package.py --config export_config.json

Config keys (see templates/export_config.example.json):
    project_dir      folder with the .kicad_pro
    name             project name (file stem)
    prefix           prefix for every output file (e.g. "MyBoard-RevB")
    output_dir       package folder; WIPED and rebuilt
    docs_dir         optional folder of hand-written docs copied into the package
    mechanical_dir   optional folder of reviewed mechanical files copied to 06-Mechanical
    facts_file       where to write the facts JSON
    kicad_cli        path to kicad-cli (KiCad 10)
    gerber_layers    comma list for kicad-cli
    not_assembled_refs        regex of references kept out of BOM and CPL
    not_assembled_footprints  regex of footprint names kept out of the CPL
    render_3d        true/false (STEP + PNG renders take minutes)

Needs openpyxl.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BOM_FIELDS = [
    "Reference",
    "${QUANTITY}",
    "Value",
    "Footprint",
    "Manufacturer",
    "MPN",
    "Description",
    "Package",
    "Preferred Supplier",
    "Status",
    "DigiKey Part #",
    "DigiKey Stock",
    "Mouser Part #",
    "Mouser Stock",
    "element14 India Part #",
    "element14 India Stock",
    "Robu Part #",
    "Robu Stock",
    "LCSC Part #",
    "LCSC Stock",
    "India Alt Supplier",
    "India Alt Part #",
    "Stock Last Checked",
    "${DNP}",
    "${EXCLUDE_FROM_BOM}",
]
SOURCE_SKIP = {".history", "__pycache__", "downloads", "dosnloads"}
SOURCE_SKIP_SUFFIX = {".kicad_prl", ".lck", ".bak", ".zip"}
DEFAULT_LAYERS = (
    "F.Cu,In1.Cu,In2.Cu,In3.Cu,In4.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,"
    "F.Silkscreen,B.Silkscreen,Edge.Cuts"
)


class Ctx:
    def __init__(self, cfg: dict, base: Path):
        def p(k):
            return (base / cfg[k]).resolve()

        self.project = p("project_dir")
        self.name = cfg["name"]
        self.pcb = self.project / f"{self.name}.kicad_pcb"
        self.sch = self.project / f"{self.name}.kicad_sch"
        self.prefix = cfg["prefix"]
        self.out = p("output_dir")
        self.docs = p("docs_dir") if cfg.get("docs_dir") else None
        self.mechanical = p("mechanical_dir") if cfg.get("mechanical_dir") else None
        self.facts = p("facts_file")
        self.cli = Path(cfg.get("kicad_cli", "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"))
        self.layers = cfg.get("gerber_layers", DEFAULT_LAYERS)
        self.not_ref = re.compile(cfg.get("not_assembled_refs", r"^(TP.*|FID\d+|MH\d+|LOGO\d*)$"))
        self.not_fp = re.compile(cfg.get("not_assembled_footprints", r"FID|MountingHole|MH_"), re.I)
        self.non_cpl_refs = set(cfg.get("non_cpl_refs", []))
        self.render = cfg.get("render_3d", True)
        self.dirs = {
            "sch": self.out / "01-Schematics",
            "pcb": self.out / "02-PCB-Layout",
            "rep": self.out / "03-ERC-DRC-Reports",
            "fab": self.out / "04-Fabrication",
            "asm": self.out / "05-Assembly",
            "bom": self.out / "05-Assembly" / "BOM",
            "img": self.out / "02-PCB-Layout" / "3D-Views",
        }

    def kicad(self, *args: str, check: bool = True) -> str:
        r = subprocess.run(
            [str(self.cli), *args],
            cwd=self.project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and r.returncode != 0:
            raise RuntimeError(f"kicad-cli {' '.join(args[:3])} failed:\n{r.stdout}\n{r.stderr}")
        return r.stdout + r.stderr


def natural(ref: str):
    m = re.match(r"([A-Za-z_#-]*)(\d*)", ref)
    return (m.group(1), int(m.group(2) or 0), ref)


def write_xlsx(path: Path, title: str, header: list, rows: list) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(header)
    for r in rows:
        ws.append(r)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for i, col in enumerate(ws.columns, 1):
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def fresh_output(c: Ctx) -> None:
    if (
        c.out == Path(c.out.anchor)
        or c.out == c.project
        or c.out.is_relative_to(c.project)
        or c.project.is_relative_to(c.out)
    ):
        raise ValueError(f"output must stay outside the source project: {c.out}")
    for label, source in (("docs_dir", c.docs), ("mechanical_dir", c.mechanical)):
        if source and (
            source == c.out or source.is_relative_to(c.out) or c.out.is_relative_to(source)
        ):
            raise ValueError(f"{label} and output directory must be separate")
    if c.out.exists():
        shutil.rmtree(c.out)
    for d in c.dirs.values():
        d.mkdir(parents=True, exist_ok=True)


def export_source_zip(c: Ctx) -> int:
    target = c.dirs["pcb"] / f"{c.prefix}-KiCad-Source.zip"
    n = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(c.project.rglob("*")):
            rel = path.relative_to(c.project)
            if (
                not path.is_file()
                or any(part in SOURCE_SKIP or part.endswith("-backups") for part in rel.parts)
                or path.suffix in SOURCE_SKIP_SUFFIX
                or path.name.startswith(("~", "_autosave"))
            ):
                continue
            z.write(path, Path(f"{c.prefix}-KiCad") / rel)
            n += 1
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
    return n


def summarize(report: Path) -> dict:
    lines = report.read_text(encoding="utf-8", errors="replace").splitlines()
    counts = Counter()
    for i, line in enumerate(lines):
        m = re.match(r"\[(\w+)\]", line)
        if m and i + 1 < len(lines):
            sev = "error" if lines[i + 1].strip().endswith("error") else "warning"
            counts[(m.group(1), sev)] += 1
    by = Counter()
    for (_, sev), n in counts.items():
        by[sev] += n
    return {
        "errors": by["error"],
        "warnings": by["warning"],
        "items": [{"rule": r, "severity": s, "count": n} for (r, s), n in counts.most_common()],
    }


def export_reports(c: Ctx) -> dict:
    erc = c.dirs["rep"] / f"{c.prefix}-ERC-Report.rpt"
    drc = c.dirs["rep"] / f"{c.prefix}-DRC-Report.rpt"
    c.kicad("sch", "erc", "--severity-all", "-o", str(erc), str(c.sch), check=False)
    c.kicad(
        "pcb",
        "drc",
        "--schematic-parity",
        "--refill-zones",
        "--severity-all",
        "-o",
        str(drc),
        str(c.pcb),
        check=False,
    )
    return {"erc": summarize(erc), "drc": summarize(drc)}


def export_fabrication(c: Ctx) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        c.kicad(
            "pcb",
            "export",
            "gerbers",
            "-l",
            c.layers,
            "--subtract-soldermask",
            "--check-zones",
            "-o",
            str(tmp),
            str(c.pcb),
        )
        c.kicad(
            "pcb",
            "export",
            "drill",
            "--format",
            "excellon",
            "--excellon-separate-th",
            "-u",
            "mm",
            "--generate-map",
            "--map-format",
            "pdf",
            "--generate-report",
            "--report-path",
            str(tmp / "drill-report.txt"),
            "-o",
            str(tmp),
            str(c.pcb),
        )
        names = []
        with zipfile.ZipFile(
            c.dirs["fab"] / f"{c.prefix}-Gerber.zip", "w", zipfile.ZIP_DEFLATED
        ) as z:
            for f in sorted(tmp.iterdir()):
                if f.suffix.lower() in {".pdf", ".txt"}:
                    continue
                arc = f.name.replace(c.name, c.prefix)
                if f.suffix == ".gbrjob":
                    z.writestr(arc, f.read_text(encoding="utf-8").replace(c.name, c.prefix))
                else:
                    z.write(f, arc)
                names.append(arc)
        for f in tmp.glob("*.pdf"):
            kind = "Non-Plated" if "NPTH" in f.name else "Plated"
            shutil.copyfile(f, c.dirs["fab"] / f"{c.prefix}-Drill-Map-{kind}.pdf")
        report = (tmp / "drill-report.txt").read_text(encoding="utf-8", errors="replace")
        shutil.copyfile(tmp / "drill-report.txt", c.dirs["fab"] / f"{c.prefix}-Drill-Report.txt")
    c.kicad(
        "pcb",
        "export",
        "ipcd356",
        "-o",
        str(c.dirs["fab"] / f"{c.prefix}-Electrical-Test-Netlist.d356"),
        str(c.pcb),
    )
    c.kicad(
        "pcb",
        "export",
        "pdf",
        "-l",
        "Edge.Cuts,Cmts.User,Dwgs.User",
        "--ibt",
        "--mode-single",
        "-o",
        str(c.dirs["fab"] / f"{c.prefix}-Fabrication-Drawing.pdf"),
        str(c.pcb),
    )
    return {"gerber_files": names, "drill_report": report}


def export_assembly_drawings(c: Ctx) -> None:
    c.kicad(
        "pcb",
        "export",
        "pdf",
        "-l",
        "F.Fab,Edge.Cuts",
        "--ibt",
        "--mode-single",
        "--hdnp",
        "-o",
        str(c.dirs["asm"] / f"{c.prefix}-Assembly-Drawing-Top.pdf"),
        str(c.pcb),
    )
    c.kicad(
        "pcb",
        "export",
        "pdf",
        "-l",
        "B.Fab,Edge.Cuts",
        "--ibt",
        "--mode-single",
        "--hdnp",
        "--mirror",
        "-o",
        str(c.dirs["asm"] / f"{c.prefix}-Assembly-Drawing-Bottom.pdf"),
        str(c.pcb),
    )


def footprint_kinds(c: Ctx) -> dict:
    text = c.pcb.read_text(encoding="utf-8")
    kinds = {}
    for block in re.split(r"\n\t\(footprint ", text)[1:]:
        ref = re.search(r'\(property "Reference" "([^"]+)"', block)
        if not ref:
            continue
        attr = re.search(r"\(attr ([^)]*)\)", block)
        attrs = attr.group(1).split() if attr else []
        kinds[ref.group(1)] = {
            "through_hole": "through_hole" in attrs,
            "footprint": block.split('"')[1],
            "thru_pads": len(re.findall(r'\(pad "[^"]*" thru_hole', block)),
        }
    return kinds


def export_positions(c: Ctx) -> dict:
    rows = {}
    for side in ("front", "back"):
        raw = c.dirs["asm"] / f"_pos_{side}.csv"
        c.kicad(
            "pcb",
            "export",
            "pos",
            "--side",
            side,
            "--format",
            "csv",
            "--units",
            "mm",
            "--exclude-dnp",
            "-o",
            str(raw),
            str(c.pcb),
        )
        with raw.open(encoding="utf-8") as f:
            data = [
                r
                for r in csv.DictReader(f)
                if not c.not_ref.match(r["Ref"]) and not c.not_fp.search(r["Package"])
            ]
        raw.unlink()
        label = "Top" if side == "front" else "Bottom"
        header = ["Designator", "Value", "Package", "Mid X (mm)", "Mid Y (mm)", "Rotation", "Layer"]
        out = [
            [r["Ref"], r["Val"], r["Package"], r["PosX"], r["PosY"], r["Rot"], label] for r in data
        ]
        with (c.dirs["asm"] / f"{c.prefix}-CPL-{label}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(out)
        write_xlsx(c.dirs["asm"] / f"{c.prefix}-CPL-{label}.xlsx", f"CPL {label}", header, out)
        rows[label] = [r[0] for r in out]
    return rows


def export_bom(c: Ctx) -> dict:
    raw = c.dirs["bom"] / "_bom_raw.csv"
    c.kicad(
        "sch",
        "export",
        "bom",
        "--fields",
        ",".join(BOM_FIELDS),
        "--labels",
        ",".join(BOM_FIELDS),
        "--group-by",
        "Value,Footprint,MPN",
        "--ref-range-delimiter",
        "",
        "--exclude-dnp",
        "-o",
        str(raw),
        str(c.sch),
    )
    with raw.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    raw.unlink()
    lines, skipped = [], []
    for r in rows:
        refs = [
            x.strip()
            for x in r["Reference"].split(",")
            if x.strip() and not x.strip().startswith("#")
        ]
        if r.get("${EXCLUDE_FROM_BOM}", "").strip() or not refs:
            skipped.extend(refs)
            continue
        keep = [x for x in refs if not c.not_ref.match(x)]
        skipped.extend(x for x in refs if c.not_ref.match(x))
        if keep:
            r["refs"] = keep
            lines.append(r)
    merged = {}  # same MPN + footprint under different values -> one line
    for r in lines:
        key = (r["MPN"].strip(), r["Footprint"]) if r["MPN"].strip() else id(r)
        if key in merged:
            merged[key]["refs"] += r["refs"]
            if r["Value"] not in merged[key]["Value"].split(" / "):
                merged[key]["Value"] += " / " + r["Value"]
        else:
            merged[key] = r
    lines = list(merged.values())
    for r in lines:
        r["refs"].sort(key=natural)
    lines.sort(key=lambda r: natural(r["refs"][0]))

    full_header = [
        "Line",
        "Reference Designator",
        "Quantity per PCB",
        "Value",
        "Description",
        "Manufacturer",
        "Manufacturer Part Number",
        "Footprint",
        "Package",
        "Preferred Supplier",
        "Status",
        "DigiKey Part Number",
        "DigiKey Stock",
        "Mouser Part Number",
        "Mouser Stock",
        "element14 India Part Number",
        "element14 India Stock",
        "Robu Part Number",
        "Robu Stock",
        "LCSC Part Number",
        "LCSC Stock",
        "India Alt Supplier",
        "India Alt Part Number",
        "Stock Checked",
    ]

    def g(r, k):
        return r.get(k, "") or ""

    full = [
        [
            i,
            ", ".join(r["refs"]),
            len(r["refs"]),
            g(r, "Value"),
            g(r, "Description"),
            g(r, "Manufacturer"),
            g(r, "MPN"),
            g(r, "Footprint").split(":")[-1],
            g(r, "Package"),
            g(r, "Preferred Supplier"),
            g(r, "Status"),
            g(r, "DigiKey Part #"),
            g(r, "DigiKey Stock"),
            g(r, "Mouser Part #"),
            g(r, "Mouser Stock"),
            g(r, "element14 India Part #"),
            g(r, "element14 India Stock"),
            g(r, "Robu Part #"),
            g(r, "Robu Stock"),
            g(r, "LCSC Part #"),
            g(r, "LCSC Stock"),
            g(r, "India Alt Supplier"),
            g(r, "India Alt Part #"),
            g(r, "Stock Last Checked"),
        ]
        for i, r in enumerate(lines, 1)
    ]
    write_xlsx(c.dirs["bom"] / f"{c.prefix}-BOM.xlsx", "BOM", full_header, full)
    with (c.dirs["bom"] / f"{c.prefix}-BOM.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(full_header)
        w.writerows(full)

    pp_header = [
        "Sr#",
        "Reference Designator",
        "Manufacturer Name",
        "Manufacturer Part Number",
        "Quantity per PCB",
        "Description",
        "Value",
        "PCB Footprint",
        "DigiKey Part Number",
        "Mouser Part Number",
        "element14 India Part Number",
    ]
    pp = [
        [
            i,
            ", ".join(r["refs"]),
            g(r, "Manufacturer"),
            g(r, "MPN"),
            len(r["refs"]),
            g(r, "Description"),
            g(r, "Value"),
            g(r, "Footprint").split(":")[-1],
            g(r, "DigiKey Part #"),
            g(r, "Mouser Part #"),
            g(r, "element14 India Part #"),
        ]
        for i, r in enumerate(lines, 1)
    ]
    write_xlsx(c.dirs["bom"] / f"{c.prefix}-BOM-PCB-Power.xlsx", "PowerBoM", pp_header, pp)

    for label, col, stock in (
        ("DigiKey", "DigiKey Part #", "DigiKey Stock"),
        ("Mouser", "Mouser Part #", "Mouser Stock"),
        ("element14-India", "element14 India Part #", "element14 India Stock"),
        ("Robu", "Robu Part #", "Robu Stock"),
    ):
        header = [
            "Reference Designator",
            "Quantity per PCB",
            "Manufacturer",
            "Manufacturer Part Number",
            f"{label} Part Number",
            "Stock",
            "Description",
        ]
        data = [
            [
                ", ".join(r["refs"]),
                len(r["refs"]),
                g(r, "Manufacturer"),
                g(r, "MPN"),
                g(r, col),
                g(r, stock),
                g(r, "Description"),
            ]
            for r in lines
            if g(r, col).strip()
        ]
        write_xlsx(c.dirs["bom"] / f"{c.prefix}-BOM-{label}.xlsx", label, header, data)

    return {
        "lines": len(lines),
        "parts": sum(len(r["refs"]) for r in lines),
        "refs": [x for r in lines for x in r["refs"]],
        "excluded": sorted(set(skipped), key=natural),
        "missing_mpn": [
            ", ".join(r["refs"]) + f" ({g(r, 'Value')})" for r in lines if not g(r, "MPN").strip()
        ],
        "no_distributor_number": [
            ", ".join(r["refs"]) + f" ({g(r, 'MPN') or g(r, 'Value')})"
            for r in lines
            if not any(
                g(r, k).strip()
                for k in ("DigiKey Part #", "Mouser Part #", "element14 India Part #")
            )
        ],
        "status": Counter(g(r, "Status") or "(blank)" for r in lines),
    }


def export_3d(c: Ctx) -> dict:
    step = c.dirs["pcb"] / f"{c.prefix}-3D.step"
    log = c.kicad(
        "pcb",
        "export",
        "step",
        "--force",
        "--subst-models",
        "--no-dnp",
        "--include-tracks",
        "--include-pads",
        "--include-silkscreen",
        "--include-soldermask",
        "-o",
        str(step),
        str(c.pcb),
    )
    c.kicad(
        "pcb",
        "export",
        "step",
        "--force",
        "--board-only",
        "-o",
        str(c.dirs["pcb"] / f"{c.prefix}-3D-Board-Only.step"),
        str(c.pcb),
    )
    views = {
        "Top": ["--side", "top"],
        "Bottom": ["--side", "bottom"],
        "Isometric-Top": [
            "--side",
            "top",
            "--rotate",
            "-45,0,45",
            "--perspective",
            "--zoom",
            "0.85",
        ],
        "Isometric-Bottom": [
            "--side",
            "bottom",
            "--rotate",
            "45,0,-45",
            "--perspective",
            "--zoom",
            "0.85",
        ],
    }
    for view, args in views.items():
        c.kicad(
            "pcb",
            "render",
            *args,
            "--quality",
            "high",
            "--background",
            "opaque",
            "--floor",
            "-w",
            "2400",
            "-h",
            "1600",
            "-o",
            str(c.dirs["img"] / f"{c.prefix}-{view}.png"),
            str(c.pcb),
        )
    missing = sorted(
        set(
            re.findall(
                r"(?:Could not|cannot|not found)[^\n]*?([\w\-. ]+\.(?:step|stp|wrl))", log, re.I
            )
        )
    )
    return {"step_mb": round(step.stat().st_size / 1e6, 1), "model_warnings": missing}


def board_stats(c: Ctx) -> dict:
    target = c.dirs["fab"] / f"{c.prefix}-Board-Statistics.txt"
    c.kicad("pcb", "export", "stats", "-o", str(target), str(c.pcb))
    text = target.read_text(encoding="utf-8", errors="replace")

    def get(key):
        return float((re.search(rf"- {key}: ([\d.]+)", text) or [0, 0])[1])

    return {
        "width_mm": get("Width"),
        "height_mm": get("Height"),
        "thickness_mm": get("Board stackup thickness"),
        "through_vias": int(get("Through vias")),
        "min_drill_mm": get("Min drill diameter"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg_path = Path(args.config).resolve()
    c = Ctx(json.loads(cfg_path.read_text(encoding="utf-8-sig")), cfg_path.parent)
    assert c.cli.exists(), f"kicad-cli not found at {c.cli}"
    assert c.pcb.exists() and c.sch.exists(), "project files not found"

    fresh_output(c)
    info = {
        "generated": date.today().isoformat(),
        "kicad": c.kicad("version").strip(),
        "board": board_stats(c),
    }
    c.kicad(
        "sch", "export", "pdf", "-o", str(c.dirs["sch"] / f"{c.prefix}-Schematic.pdf"), str(c.sch)
    )
    info["source_files"] = export_source_zip(c)
    info["reports"] = export_reports(c)
    info["fabrication"] = export_fabrication(c)
    export_assembly_drawings(c)
    kinds = footprint_kinds(c)
    info["bom"] = export_bom(c)
    placed = export_positions(c)
    info["placement"] = {s: len(r) for s, r in placed.items()}
    cpl, bom = set(placed["Top"]) | set(placed["Bottom"]), set(info["bom"]["refs"]) - c.non_cpl_refs
    info["non_cpl_hardware"] = sorted(set(info["bom"]["refs"]) & c.non_cpl_refs, key=natural)
    info["bom_not_in_cpl"] = sorted(bom - cpl, key=natural)
    info["cpl_not_in_bom"] = sorted(cpl - bom, key=natural)
    assembled = [r for r in info["bom"]["refs"] if r in kinds]
    info["mount"] = {
        "through_hole": sorted(
            [r for r in assembled if kinds[r]["through_hole"] or kinds[r]["thru_pads"]], key=natural
        ),
        "side": {
            r: "Top" if r in placed["Top"] else "Bottom" if r in placed["Bottom"] else "?"
            for r in assembled
        },
    }
    if c.render:
        info["three_d"] = export_3d(c)
    if c.docs and c.docs.exists():
        for src in c.docs.rglob("*"):
            if src.is_file():
                dst = c.out / src.relative_to(c.docs)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
    if c.mechanical:
        if not c.mechanical.is_dir():
            raise FileNotFoundError(f"mechanical_dir does not exist: {c.mechanical}")
        for src in c.mechanical.rglob("*"):
            if src.is_file():
                dst = c.out / "06-Mechanical" / src.relative_to(c.mechanical)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
    from package_preflight import finalize

    finalize(c, info)
    c.facts.write_text(json.dumps(info, indent=2, default=str) + "\n", encoding="utf-8")
    summary = {
        k: info[k] for k in ("generated", "board", "placement", "bom_not_in_cpl", "cpl_not_in_bom")
    }
    summary["bom"] = {k: info["bom"][k] for k in ("lines", "parts", "missing_mpn")}
    summary["erc"] = info["reports"]["erc"]["errors"]
    summary["drc"] = info["reports"]["drc"]["errors"]
    summary["through_hole"] = len(info["mount"]["through_hole"])
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
