#!/usr/bin/env python3
"""Build a checked PCBWay fabrication and assembly package from KiCad 10 files.

The design sources are read-only. Existing output is replaced only when the caller
passes --replace-output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

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
    "Distributor Part Number",
    "DigiKey Part #",
    "Mouser Part #",
    "LCSC Part #",
    "PCBWay Source Mode",
    "Assembly Notes",
    "Approved Alternate MPNs",
    "${DNP}",
    "${EXCLUDE_FROM_BOM}",
]

PCBWAY_BOM_HEADER = [
    "Line #",
    "Quantity Per PCB",
    "Reference Designator",
    "Part Number",
    "Part Description",
    "Package",
    "Type (SMD/THT)",
    "Manufacturer Name",
    "Manufacturer Part Number",
    "Distributor Part Number",
    "Source Mode",
    "Customer Instructions / Notes",
]

CENTROID_HEADER = [
    "Designator",
    "Value",
    "Package",
    "X (mm)",
    "Y (mm)",
    "Rotation (deg)",
    "Side",
]

SOURCE_URLS = {
    "fabrication_capabilities": "https://www.pcbway.com/capabilities.html",
    "stackups": "https://www.pcbway.com/multi-layer-laminated-structure.html",
    "assembly_capabilities": "https://www.pcbway.com/assembly-capabilities.html",
    "assembly_files": "https://m.pcbway.com/assembly-file-requirements.html",
}

SOURCE_SKIP_DIRS = {".git", ".history", "__pycache__", "downloads", "dosnloads"}
SOURCE_SKIP_SUFFIXES = {".kicad_prl", ".lck", ".bak", ".zip"}
SOURCE_ALLOWED_SUFFIXES = {
    ".kicad_pcb",
    ".kicad_sch",
    ".kicad_pro",
    ".kicad_sym",
    ".kicad_mod",
    ".kicad_dru",
    ".kicad_wks",
    ".step",
    ".stp",
    ".wrl",
    ".stl",
    ".igs",
    ".iges",
    ".svg",
    ".dxf",
    ".lib",
    ".dcm",
}
SOURCE_ALLOWED_NAMES = {"fp-lib-table", "sym-lib-table"}


def natural(value: str) -> tuple[str, int, str]:
    match = re.match(r"([A-Za-z_#-]*)(\d*)", value)
    assert match
    return match.group(1), int(match.group(2) or 0), value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_xlsx(path: Path, title: str, header: list[str], rows: list[list[Any]]) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = title[:31]
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for index, column in enumerate(sheet.columns, 1):
        width = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[get_column_letter(index)].width = min(max(12, width + 2), 64)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(path)


def extract_parenthesized(text: str, start: int) -> str:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unbalanced KiCad s-expression")


def enabled_copper_layers(board_text: str) -> list[str]:
    start = board_text.find("(layers")
    if start < 0:
        raise ValueError("board has no layers block")
    block = extract_parenthesized(board_text, start)
    layers = re.findall(r'\(\d+\s+"([^"]+\.Cu)"\s+(?:signal|power|mixed|jumper)', block)
    if len(layers) < 2:
        raise ValueError("could not determine enabled copper layers")
    return layers


def footprint_kinds(board_text: str) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for match in re.finditer(r"\(footprint\s", board_text):
        block = extract_parenthesized(board_text, match.start())
        ref = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if not ref:
            continue
        attr = re.search(r"\(attr\s+([^)]*)\)", block)
        attributes = set(attr.group(1).split()) if attr else set()
        has_tht_pad = bool(re.search(r'\(pad\s+"[^"]*"\s+thru_hole\b', block))
        kinds[ref.group(1)] = "THT" if "through_hole" in attributes or has_tht_pad else "SMD"
    return kinds


def summarize_report(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    findings = re.findall(r"(?m)^\s*\[[^\]]+\][^\n]*(?:\n[^\n]*)?", text)
    errors = sum(bool(re.search(r"\berror\b", item, re.I)) for item in findings)
    warnings = sum(bool(re.search(r"\bwarning\b", item, re.I)) for item in findings)
    return {
        "exists": path.exists(),
        "findings_detected": len(findings),
        "errors_detected": errors,
        "warnings_detected": warnings,
    }


class Context:
    def __init__(self, config: dict[str, Any], config_path: Path):
        base = config_path.parent

        def resolve(key):
            return (base / config[key]).resolve()

        self.config = config
        self.project = resolve("project_dir")
        self.name = config["name"]
        self.prefix = config["prefix"]
        self.board = self.project / f"{self.name}.kicad_pcb"
        self.schematic = self.project / f"{self.name}.kicad_sch"
        self.output = resolve("output_dir")
        self.docs = resolve("docs_dir") if config.get("docs_dir") else None
        self.mechanical = resolve("mechanical_dir") if config.get("mechanical_dir") else None
        self.cli = Path(config.get("kicad_cli", "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"))
        self.use_origin = bool(config.get("use_auxiliary_origin", True))
        self.not_ref = re.compile(
            config.get("not_assembled_refs", r"^(TP.*|FID\d+|MH\d+|LOGO\d*)$")
        )
        self.not_footprint = re.compile(
            config.get("not_assembled_footprints", r"FID|MountingHole|MH_"), re.I
        )
        self.render = bool(config.get("render_3d", True))
        self.pcbway = config.get("pcbway", {})
        facts_value = Path(config.get("facts_file", "EXPORT-FACTS.json"))
        self.facts = facts_value if facts_value.is_absolute() else self.output / facts_value.name
        self.dirs = {
            "schematics": self.output / "01-Schematics",
            "layout": self.output / "02-PCB-Layout",
            "layout_renders": self.output / "02-PCB-Layout" / "3D-Views",
            "reports": self.output / "03-ERC-DRC-Reports",
            "fab": self.output / "04-Fabrication",
            "assembly": self.output / "05-Assembly",
            "bom": self.output / "05-Assembly" / "BOM",
            "renders": self.output / "05-Assembly" / "Renders",
            "mechanical": self.output / "06-Mechanical",
            "ordering": self.output / "07-Ordering-PCBWay",
            "bringup": self.output / "08-Bring-Up-Test-Plan",
            "reference": self.output / "09-Reference",
        }

    def validate(self) -> None:
        if not self.cli.is_file():
            raise FileNotFoundError(f"kicad-cli not found: {self.cli}")
        if not self.board.is_file() or not self.schematic.is_file():
            raise FileNotFoundError("matching .kicad_pcb and .kicad_sch files are required")
        for label, source in (("docs_dir", self.docs), ("mechanical_dir", self.mechanical)):
            if source and (
                source == self.output
                or self.output.is_relative_to(source)
                or source.is_relative_to(self.output)
            ):
                raise ValueError(f"{label} and output directory must be separate")
        mode = self.pcbway.get("assembly_mode")
        if mode not in {"turnkey", "partial_turnkey", "consigned"}:
            raise ValueError("pcbway.assembly_mode must be turnkey, partial_turnkey, or consigned")
        layer_count = self.pcbway.get("layer_count")
        if layer_count is not None and int(layer_count) < 2:
            raise ValueError("pcbway.layer_count, if supplied, must be at least two")

    def run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(self.cli), *arguments],
            cwd=self.project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode:
            command = " ".join(arguments[:4])
            raise RuntimeError(f"kicad-cli {command} failed:\n{result.stdout}\n{result.stderr}")
        return result


def prepare_output(context: Context, replace: bool) -> None:
    target = context.output.resolve()
    project = context.project.resolve()
    if (
        target == Path(target.anchor)
        or project == target
        or project.is_relative_to(target)
        or target.is_relative_to(project)
    ):
        raise ValueError(f"unsafe output directory: {target}")
    if target.exists():
        if not replace:
            raise FileExistsError(
                f"output exists; inspect it or rerun with --replace-output: {target}"
            )
        prior_facts = context.facts.is_relative_to(target) and context.facts.is_file()
        prior_manifest = (target / "SHA256SUMS.json").is_file() or (
            target / "01-Reports" / "SHA256SUMS.json"
        ).is_file()
        if not (prior_facts or prior_manifest):
            raise ValueError(
                f"refusing to replace a directory without a prior PCBWay export marker: {target}"
            )
        shutil.rmtree(target)
    for directory in context.dirs.values():
        directory.mkdir(parents=True, exist_ok=True)


def gerber_layers(context: Context, copper: list[str]) -> list[str]:
    configured = context.config.get("gerber_layers", "auto")
    if configured != "auto":
        return [item.strip() for item in str(configured).split(",") if item.strip()]
    return [
        *copper,
        "F.Mask",
        "B.Mask",
        "F.Paste",
        "B.Paste",
        "F.Silkscreen",
        "B.Silkscreen",
        "Edge.Cuts",
    ]


def export_reports(context: Context) -> dict[str, Any]:
    erc = context.dirs["reports"] / f"{context.prefix}-ERC.rpt"
    drc = context.dirs["reports"] / f"{context.prefix}-DRC.rpt"
    erc_run = context.run(
        "sch", "erc", "--severity-all", "-o", str(erc), str(context.schematic), check=False
    )
    drc_run = context.run(
        "pcb",
        "drc",
        "--schematic-parity",
        "--refill-zones",
        "--severity-all",
        "-o",
        str(drc),
        str(context.board),
        check=False,
    )
    return {
        "erc": {**summarize_report(erc), "return_code": erc_run.returncode},
        "drc": {**summarize_report(drc), "return_code": drc_run.returncode},
    }


def export_fabrication(context: Context, layers: list[str]) -> dict[str, Any]:
    target_zip = context.dirs["fab"] / f"{context.prefix}-PCBWay-Gerber.zip"
    origin_gerber = ["--use-drill-file-origin"] if context.use_origin else []
    origin_drill = ["--drill-origin", "plot"] if context.use_origin else []
    with tempfile.TemporaryDirectory(prefix="pcbway-gerber-") as temp_name:
        temp = Path(temp_name)
        context.run(
            "pcb",
            "export",
            "gerbers",
            "--layers",
            ",".join(layers),
            "--no-x2",
            "--no-netlist",
            "--subtract-soldermask",
            "--check-zones",
            *origin_gerber,
            "-o",
            str(temp),
            str(context.board),
        )
        context.run(
            "pcb",
            "export",
            "drill",
            "--format",
            "excellon",
            "--excellon-units",
            "mm",
            "--excellon-zeros-format",
            "decimal",
            "--excellon-oval-format",
            "route",
            "--excellon-separate-th",
            "--generate-map",
            "--map-format",
            "pdf",
            "--generate-report",
            "--report-path",
            str(temp / "drill-report.txt"),
            *origin_drill,
            "-o",
            str(temp),
            str(context.board),
        )
        archive_names: list[str] = []
        gerber_job_general: dict[str, Any] = {}
        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(temp.iterdir()):
                if path.suffix.lower() in {".pdf", ".txt"}:
                    continue
                name = path.name.replace(context.name, context.prefix)
                if path.suffix.lower() == ".gbrjob":
                    job = json.loads(path.read_text(encoding="utf-8"))
                    gerber_job_general = job.get("GeneralSpecs", {})
                    for item in job.get("FilesAttributes", []):
                        item["Path"] = Path(item["Path"]).name.replace(context.name, context.prefix)
                    archive.writestr(name, json.dumps(job, indent=2) + "\n")
                else:
                    archive.write(path, name)
                archive_names.append(name)
        with zipfile.ZipFile(target_zip) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Gerber ZIP integrity check failed")
        for path in temp.glob("*.pdf"):
            shutil.copy2(
                path, context.dirs["fab"] / path.name.replace(context.name, context.prefix)
            )
        report = temp / "drill-report.txt"
        if report.exists():
            shutil.copy2(report, context.dirs["fab"] / f"{context.prefix}-Drill-Report.txt")

    context.run(
        "pcb",
        "export",
        "ipcd356",
        "-o",
        str(context.dirs["fab"] / f"{context.prefix}-Electrical-Test-Netlist.d356"),
        str(context.board),
    )
    context.run(
        "pcb",
        "export",
        "pdf",
        "--layers",
        "Edge.Cuts,Cmts.User,Dwgs.User",
        "--include-border-title",
        "--mode-single",
        "-o",
        str(context.dirs["fab"] / f"{context.prefix}-Fabrication-Drawing.pdf"),
        str(context.board),
    )
    return {
        "zip": target_zip.name,
        "files": archive_names,
        "layers_requested": layers,
        "gerber_job_general": gerber_job_general,
    }


def check_fabrication_archive(
    context: Context, fabrication: dict[str, Any], copper_layers: list[str]
) -> list[str]:
    errors: list[str] = []
    target = context.dirs["fab"] / fabrication["zip"]
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        if archive.testzip() is not None:
            errors.append("Gerber archive has a corrupt member")
        jobs = [name for name in names if name.endswith(".gbrjob")]
        if len(jobs) != 1:
            errors.append("Gerber archive must contain exactly one job file")
        else:
            job = json.loads(archive.read(jobs[0]))
            attrs = job.get("FilesAttributes", [])
            for item in attrs:
                if item.get("Path") not in names:
                    errors.append(f"Gerber job references missing file: {item.get('Path')}")
            if sum(item.get("FileFunction", "").startswith("Copper,") for item in attrs) != len(
                copper_layers
            ):
                errors.append("Gerber copper layer count differs from enabled board copper layers")
            if not any(item.get("FileFunction") == "Profile" for item in attrs):
                errors.append("Gerber job lacks board outline profile")
        if not any(name.endswith("-PTH.drl") for name in names):
            errors.append("Gerber archive lacks PTH drill file")
        if not any(name.endswith("-NPTH.drl") for name in names):
            errors.append("Gerber archive lacks NPTH drill file")
    return errors


def parse_position_rows(context: Context, footprint_types: dict[str, str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for side, label in (("front", "Top"), ("back", "Bottom")):
        with tempfile.TemporaryDirectory(prefix="pcbway-pos-") as temp_name:
            raw = Path(temp_name) / f"{side}.csv"
            origin = ["--use-drill-file-origin"] if context.use_origin else []
            context.run(
                "pcb",
                "export",
                "pos",
                "--side",
                side,
                "--format",
                "csv",
                "--units",
                "mm",
                "--smd-only",
                "--exclude-dnp",
                *origin,
                "-o",
                str(raw),
                str(context.board),
            )
            with raw.open(encoding="utf-8-sig", newline="") as stream:
                for item in csv.DictReader(stream):
                    ref = item.get("Ref", "").strip()
                    package = item.get("Package", "").strip()
                    if (
                        not ref
                        or context.not_ref.match(ref)
                        or context.not_footprint.search(package)
                    ):
                        continue
                    if footprint_types.get(ref, "SMD") != "SMD":
                        continue
                    rows.append(
                        [
                            ref,
                            item.get("Val", ""),
                            package,
                            item.get("PosX", ""),
                            item.get("PosY", ""),
                            item.get("Rot", ""),
                            label,
                        ]
                    )
    rows.sort(key=lambda row: natural(row[0]))
    path = context.dirs["assembly"] / f"{context.prefix}-PCBWay-Centroid.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(CENTROID_HEADER)
        writer.writerows(rows)
    return rows


def first_value(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def build_bom_rows(
    raw_rows: list[dict[str, str]],
    footprint_types: dict[str, str],
    not_ref: re.Pattern[str],
    assembly_mode: str,
) -> tuple[list[list[Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    excluded: list[str] = []
    for row in raw_rows:
        references = [
            ref.strip()
            for ref in (row.get("Reference") or "").split(",")
            if ref.strip() and not ref.strip().startswith("#")
        ]
        if (row.get("${EXCLUDE_FROM_BOM}") or "").strip():
            excluded.extend(references)
            continue
        keep = [ref for ref in references if not not_ref.match(ref)]
        excluded.extend(ref for ref in references if not_ref.match(ref))
        if not keep:
            continue
        keep.sort(key=natural)
        manufacturer = (row.get("Manufacturer") or "").strip()
        mpn = (row.get("MPN") or "").strip()
        footprint = (row.get("Footprint") or "").split(":")[-1]
        mount_types = {footprint_types.get(ref, "UNKNOWN") for ref in keep}
        mount = next(iter(mount_types)) if len(mount_types) == 1 else "Hybrid"
        distributor = first_value(
            row,
            ("Distributor Part Number", "DigiKey Part #", "Mouser Part #", "LCSC Part #"),
        )
        source_mode = (row.get("PCBWay Source Mode") or "").strip()
        if not source_mode:
            source_mode = "PCBWay" if assembly_mode == "turnkey" else "Customer"
        notes = (row.get("Assembly Notes") or "").strip()
        alternates = (row.get("Approved Alternate MPNs") or "").strip()
        if alternates:
            notes = "; ".join(
                item for item in (notes, f"Approved alternates: {alternates}") if item
            )
        records.append(
            {
                "refs": keep,
                "value": (row.get("Value") or "").strip(),
                "description": (row.get("Description") or "").strip(),
                "package": (row.get("Package") or footprint).strip(),
                "footprint": footprint,
                "mount": mount,
                "manufacturer": manufacturer,
                "mpn": mpn,
                "distributor": distributor,
                "source_mode": source_mode,
                "notes": notes,
            }
        )

    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, record in enumerate(records):
        key = (
            record["manufacturer"],
            record["mpn"],
            record["footprint"],
            record["source_mode"],
        )
        if not record["mpn"]:
            key = (*key, str(index))
        if key not in merged:
            merged[key] = record
        else:
            merged[key]["refs"].extend(record["refs"])
            merged[key]["refs"].sort(key=natural)
    records = sorted(merged.values(), key=lambda item: natural(item["refs"][0]))

    output: list[list[Any]] = []
    missing_mpn: list[str] = []
    missing_manufacturer: list[str] = []
    duplicate_refs: list[str] = []
    ref_counts = Counter(ref for record in records for ref in record["refs"])
    duplicate_refs.extend(
        sorted((ref for ref, count in ref_counts.items() if count > 1), key=natural)
    )
    for line, record in enumerate(records, 1):
        refs = ", ".join(record["refs"])
        pcbway_sourced = record["source_mode"].casefold() not in {"customer", "consigned"}
        if pcbway_sourced and not record["mpn"]:
            missing_mpn.append(refs)
        if pcbway_sourced and not record["manufacturer"]:
            missing_manufacturer.append(refs)
        output.append(
            [
                line,
                len(record["refs"]),
                refs,
                record["mpn"] or record["value"],
                record["description"] or record["value"],
                record["package"] or record["footprint"],
                record["mount"],
                record["manufacturer"],
                record["mpn"],
                record["distributor"],
                record["source_mode"],
                record["notes"],
            ]
        )
    facts = {
        "lines": len(output),
        "parts_per_board": sum(int(row[1]) for row in output),
        "references": [ref for record in records for ref in record["refs"]],
        "smd_references": [
            ref for record in records if record["mount"] == "SMD" for ref in record["refs"]
        ],
        "tht_references": [
            ref for record in records if record["mount"] == "THT" for ref in record["refs"]
        ],
        "excluded_references": sorted(set(excluded), key=natural),
        "missing_mpn": missing_mpn,
        "missing_manufacturer": missing_manufacturer,
        "duplicate_references": duplicate_refs,
    }
    return output, facts


def export_bom(
    context: Context, footprint_types: dict[str, str]
) -> tuple[list[list[Any]], dict[str, Any]]:
    raw = context.dirs["assembly"] / "_bom_raw.csv"
    context.run(
        "sch",
        "export",
        "bom",
        "--fields",
        ",".join(BOM_FIELDS),
        "--labels",
        ",".join(BOM_FIELDS),
        "--group-by",
        "Value,Footprint,Manufacturer,MPN,PCBWay Source Mode,Assembly Notes",
        "--ref-range-delimiter",
        "",
        "--exclude-dnp",
        "-o",
        str(raw),
        str(context.schematic),
    )
    with raw.open(encoding="utf-8-sig", newline="") as stream:
        raw_rows = list(csv.DictReader(stream))
    raw.unlink()
    rows, facts = build_bom_rows(
        raw_rows,
        footprint_types,
        context.not_ref,
        context.pcbway["assembly_mode"],
    )
    csv_path = context.dirs["assembly"] / f"{context.prefix}-PCBWay-BOM.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(PCBWAY_BOM_HEADER)
        writer.writerows(rows)
    write_xlsx(
        context.dirs["assembly"] / f"{context.prefix}-PCBWay-BOM.xlsx",
        "PCBWay BOM",
        PCBWAY_BOM_HEADER,
        rows,
    )
    write_extended_bom(context, raw_rows, set(facts["references"]))
    return rows, facts


def write_extended_bom(
    context: Context, raw_rows: list[dict[str, str]], assembled_refs: set[str]
) -> None:
    """Keep a review BOM with source fields, separate from PCBWay's upload BOM."""
    fields = [field for field in BOM_FIELDS if not field.startswith("${")]
    records: list[list[str]] = []
    for row in raw_rows:
        refs = [ref.strip() for ref in (row.get("Reference") or "").split(",")]
        retained = [ref for ref in refs if ref in assembled_refs]
        if not retained:
            continue
        record = {field: row.get(field, "") for field in fields}
        record["Reference"] = ", ".join(retained)
        record["Quantity Per PCB"] = str(len(retained))
        records.append([record.get(field, "") for field in ["Quantity Per PCB", *fields]])
    header = ["Quantity Per PCB", *fields]
    target = context.dirs["bom"]
    with (target / f"{context.prefix}-BOM-Full.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(records)
    write_xlsx(target / f"{context.prefix}-BOM-Full.xlsx", "Full BOM", header, records)
    for supplier, field in (
        ("DigiKey", "DigiKey Part #"),
        ("Mouser", "Mouser Part #"),
        ("LCSC", "LCSC Part #"),
    ):
        subset = [row for row in records if row[header.index(field)].strip()]
        if subset:
            write_xlsx(target / f"{context.prefix}-BOM-{supplier}.xlsx", supplier, header, subset)


def export_assembly_documents(context: Context) -> list[Path]:
    outputs: list[Path] = []
    for side, layers, mirror in (
        ("Top", "F.Fab,F.Silkscreen,Edge.Cuts", False),
        ("Bottom", "B.Fab,B.Silkscreen,Edge.Cuts", True),
    ):
        output = context.dirs["assembly"] / f"{context.prefix}-Assembly-Drawing-{side}.pdf"
        arguments = [
            "pcb",
            "export",
            "pdf",
            "--layers",
            layers,
            "--include-border-title",
            "--hide-DNP-footprints-on-fab-layers",
            "--mode-single",
        ]
        if mirror:
            arguments.append("--mirror")
        context.run(*arguments, "-o", str(output), str(context.board))
        outputs.append(output)
    return outputs


def write_order_specification(context: Context, copper_layers: list[str]) -> Path:
    data = context.pcbway
    output = context.dirs["assembly"] / f"{context.prefix}-PCBWay-Order-Specification.md"

    def shown(key: str, unit: str = "") -> str:
        value = data.get(key)
        return f"{value}{unit}" if value is not None and value != "" else "NOT SPECIFIED"

    rows = [
        ("Assembly mode", shown("assembly_mode")),
        ("PCB quantity", shown("pcb_quantity")),
        ("Assembled quantity", shown("assembled_quantity")),
        ("Material", shown("material")),
        ("Copper layers", len(copper_layers)),
        ("Nominal finished thickness", shown("finished_thickness_mm", " mm")),
        ("Finished outer copper", shown("finished_outer_copper_oz", " oz")),
        ("Inner copper", shown("inner_copper_oz", " oz")),
        ("Surface finish", shown("surface_finish")),
        ("Solder mask", shown("solder_mask")),
        ("Silkscreen", shown("silkscreen")),
        ("Controlled impedance", shown("controlled_impedance")),
        ("Impedance tolerance", shown("impedance_tolerance_percent", "%")),
        ("Gold fingers", shown("gold_fingers")),
        ("PCBWay standard stack-up ID", shown("standard_stackup_id")),
        ("Inner residual copper", shown("inner_residual_copper_percent", "%")),
        ("Stack-up status", shown("stackup_status")),
    ]
    table = "\n".join(f"| {key} | {value} |" for key, value in rows)
    output.write_text(
        "# PCBWay order specification\n\n"
        f"Board: {context.prefix}\n\n"
        "| Parameter | Requested value |\n|---|---|\n"
        f"{table}\n\n"
        "## Special notes\n\n"
        f"{data.get('special_notes', '')}\n\n"
        "Controlled-impedance geometry is not approved merely because this file names a target. "
        "PCBWay must confirm the production stack-up and width/gap for the released artwork.\n",
        encoding="utf-8",
    )
    return output


def export_board_statistics(context: Context) -> dict[str, float | None]:
    report = context.dirs["fab"] / f"{context.prefix}-Board-Statistics.txt"
    context.run("pcb", "export", "stats", "--units", "mm", "-o", str(report), str(context.board))
    text = report.read_text(encoding="utf-8", errors="replace")

    def number(label: str) -> float | None:
        match = re.search(rf"(?m)^\s*-\s*{re.escape(label)}:\s*([\d.]+)", text)
        return float(match.group(1)) if match else None

    return {
        "width_mm": number("Width"),
        "height_mm": number("Height"),
        "stackup_thickness_mm": number("Board stackup thickness"),
    }


def build_order_guide(context: Context, facts: dict[str, Any]) -> str:
    order = context.pcbway
    bom = facts["bom"]
    size = facts["board_statistics"]
    prefix = context.prefix
    unknown = "NOT SPECIFIED — confirm in PCBWay quote"

    def field(key: str, suffix: str = "") -> str:
        value = order.get(key)
        if value is None or value == "":
            return unknown
        return f"{value}{suffix}".replace("|", "\\|").replace("\n", " ")

    def dimension(key: str) -> str:
        value = size.get(key)
        return f"{value:g} mm" if value is not None else "NOT READ FROM BOARD"

    def yes_no(key: str) -> str:
        value = order.get(key)
        return unknown if value is None else ("Yes" if value else "No")

    centroid_count = facts["centroid_rows"]
    smd = bom["smd_references"]
    tht = bom["tht_references"]
    assembly_sides = facts["centroid_sides"]
    sides = ", ".join(assembly_sides) if assembly_sides else "No SMD placements"
    blockers = facts["unresolved_release_items"]
    blocker_lines = (
        "\n".join(f"- {item}" for item in blockers)
        or "- None detected by the exporter; engineering and CAM approval are still required."
    )
    rows = [
        ("PCB name / revision", prefix),
        ("PCB type", field("pcb_type")),
        ("Quantity of bare PCBs", field("pcb_quantity")),
        ("Quantity assembled", field("assembled_quantity")),
        ("Board width × height", f"{dimension('width_mm')} × {dimension('height_mm')}"),
        ("Finished board size tolerance", field("board_size_tolerance_mm", " mm")),
        ("Copper layers", str(len(facts["copper_layers"]))),
        ("Finished thickness requested", field("finished_thickness_mm", " mm")),
        ("Board stack-up thickness read from KiCad", dimension("stackup_thickness_mm")),
        ("Material", field("material")),
        ("High-Tg / material grade", field("material_grade")),
        ("Outer finished copper", field("finished_outer_copper_oz", " oz")),
        ("Inner copper", field("inner_copper_oz", " oz")),
        ("Surface finish", field("surface_finish")),
        ("Solder mask", field("solder_mask")),
        ("Legend", field("silkscreen")),
        ("Panelization / rails", field("panelization")),
        ("Via treatment / fill", field("via_treatment")),
        ("Controlled impedance", yes_no("controlled_impedance")),
        ("Impedance tolerance", field("impedance_tolerance_percent", "%")),
        ("PCBWay stack-up ID", field("standard_stackup_id")),
        ("Stack-up approval", field("stackup_status")),
        ("Inner residual copper ratio", field("inner_residual_copper_percent", "%")),
        ("Gold fingers", yes_no("gold_fingers")),
        ("RoHS / lead-free process", field("lead_free_process")),
        ("Electrical test / IPC class", field("electrical_test_and_ipc_class")),
        ("Stencil / paste service", field("stencil_service")),
        ("Assembly testing / inspection", field("assembly_testing")),
        ("Conformal coating", field("conformal_coating")),
        ("Cleaning", field("cleaning")),
        ("CAM / production data approval", field("data_approval")),
        ("PCB lead time", field("pcb_lead_time")),
        ("Assembly lead time", field("assembly_lead_time")),
        ("Component sourcing lead time", field("sourcing_lead_time")),
        ("Assembly mode", field("assembly_mode")),
        ("Assembled sides from centroid", sides),
        ("SMD placements per board", str(len(smd))),
        ("Through-hole placements per board", str(len(tht))),
        ("BOM parts per board", str(bom["parts_per_board"])),
    ]
    table = "\n".join(f"| {key} | {value} |" for key, value in rows)
    upload = [
        ("PCB fabrication Gerber upload", f"../04-Fabrication/{prefix}-PCBWay-Gerber.zip"),
        ("PCBWay BOM upload", f"../05-Assembly/{prefix}-PCBWay-BOM.xlsx"),
        ("Centroid / pick-and-place upload", f"../05-Assembly/{prefix}-PCBWay-Centroid.csv"),
        ("Assembly Other Files", f"../05-Assembly/{prefix}-PCBWay-Assembly-Other-Files.zip"),
        (
            "Fabrication drawing for CAM review",
            f"../04-Fabrication/{prefix}-Fabrication-Drawing.pdf",
        ),
        ("ERC and DRC evidence", "../03-ERC-DRC-Reports/"),
    ]
    upload_table = "\n".join(f"| {label} | `{path}` |" for label, path in upload)
    notes = str(order.get("special_notes") or "No special notes supplied.")
    return (
        "# How to order this board from PCBWay\n\n"
        f"Board: **{prefix}** · Package generated: **{facts['generated']}** · "
        f"Release state: "
        f"**{'HOLD' if blockers else 'EXPORT CHECKS PASSED — CAM APPROVAL PENDING'}**.\n\n"
        "## 1. Upload the fabrication data\n\n"
        "Create or open the PCBWay PCB fabrication quote. Enter the board parameters below; "
        "upload only the Gerber ZIP in the fabrication upload. "
        "Keep the BOM and centroid as separate assembly "
        "uploads.\n\n"
        "## 2. Enter the order fields\n\n| Field | Value from config or board |\n|---|---|\n"
        f"{table}\n\n"
        "Values marked **NOT SPECIFIED** are decisions for the quote, not inferred defaults. "
        "The KiCad stack-up thickness is a board-file reading, not PCBWay approval.\n\n"
        "## 3. Add PCB assembly and source the parts\n\n"
        f"Choose **{field('assembly_mode')}** sourcing and enter "
        f"**{field('assembled_quantity')}** assembled boards. "
        f"The BOM contains **{bom['parts_per_board']}** placements per board: "
        f"**{len(smd)} SMD** and **{len(tht)} through-hole**; centroid rows: **{centroid_count}**, "
        f"on **{sides}**. PCBWay-sourced lines require exact manufacturer and MPN. "
        "Customer-supplied lines use the packing list in Assembly Other Files when present. "
        "Any substitute requires explicit approval.\n\n"
        "## 4. Upload map\n\n| PCBWay upload or reviewer | File in this package |\n|---|---|\n"
        f"{upload_table}\n\n"
        "The Assembly Other Files ZIP contains drawings, an "
        "order specification and optional renders. "
        "The Gerber ZIP is fabrication data only.\n\n"
        "## 5. Controlled impedance and CAM handoff\n\n"
        f"PCBWay standard stack-up ID: **{field('standard_stackup_id')}**. "
        f"Approval state: **{field('stackup_status')}**. "
        "Send the fabrication drawing, actual "
        "routed-layer/trace-width/gap schedule, target "
        "impedances, "
        "reference planes and tolerance to PCBWay. The selected "
        "construction and production geometry need "
        "written confirmation before fabrication.\n\n"
        f"Special notes: {notes}\n\n"
        "## 6. Release hold and final review\n\n"
        f"{blocker_lines}\n\n"
        "Check the online quote against these fields, assembly population, panelization, "
        "component substitutions and the reviewed CAM response before placing the order. "
        "This file is an ordering guide, not an approved fabrication drawing.\n\n"
        "PCBWay references: [PCBA file "
        "requirements](https://www.pcbway.com/assembly-file-requirements.html) "
        "and [assembly upload flow](https://www.pcbway.com/helpcenter/pcb_assembly_ordering/How_to_Upload_PCB_Assembly_PCBA__Inquiry.html).\n"
    )


def write_order_guide(context: Context, facts: dict[str, Any]) -> Path:
    output = context.dirs["ordering"] / "HOW-TO-ORDER-FROM-PCBWAY.md"
    output.write_text(build_order_guide(context, facts), encoding="utf-8")
    return output


def write_package_documents(context: Context, facts: dict[str, Any]) -> list[str]:
    """Generate board-specific handoff documents without inventing quote choices."""
    order = context.pcbway
    size = facts["board_statistics"]
    missing = "NOT SPECIFIED — confirm before order"

    def option(key: str, unit: str = "") -> str:
        value = order.get(key)
        return f"{value}{unit}" if value is not None and value != "" else missing

    def metric(key: str) -> str:
        value = size.get(key)
        return f"{value:g} mm" if value is not None else "NOT READ FROM BOARD"

    copper = ", ".join(facts["copper_layers"])
    blockers = "\n".join(f"- {item}" for item in facts["unresolved_release_items"])
    if not blockers:
        blockers = "- None found by automated checks; review still required."
    readme = context.output / "README.md"
    readme.write_text(
        f"# {context.prefix} — PCBWay manufacturing deliverable\n\n"
        f"Generated {facts['generated']} from `{context.board.name}`. "
        f"Status: "
        f"**{'HOLD' if facts['unresolved_release_items'] else 'EXPORT CHECKS PASSED — CAM APPROVAL PENDING'}**.\n\n"  # noqa: E501 - composed report text or resource path
        "| Folder | Contents |\n|---|---|\n"
        "| `01-Schematics` | Schematic PDF |\n"
        "| `02-PCB-Layout` | Filtered KiCad source ZIP; "
        "detailed, fit-check and bare-board STEP plus four 3D "
        "views when rendering is enabled |\n"
        "| `03-ERC-DRC-Reports` | ERC and DRC reports |\n"
        "| `04-Fabrication` | PCBWay Gerber/drill ZIP, drill "
        "maps, IPC-D-356, board statistics, fabrication drawing "
        "and specification |\n"
        "| `05-Assembly` | PCBWay BOM and centroid, "
        "full/distributor review BOMs, assembly drawings and "
        "other-files ZIP |\n"
        "| `06-Mechanical` | Supplied mechanical drawings and notes, if any |\n"
        "| `07-Ordering-PCBWay` | Board-specific ordering guide and upload map |\n"
        "| `08-Bring-Up-Test-Plan` | Structured test-plan handoff |\n"
        "| `09-Reference` | Other supplied project documents |\n\n"
        f"Board dimensions: **{metric('width_mm')} × {metric('height_mm')}**; "
        f"{len(facts['copper_layers'])} copper layers; "
        f"{facts['bom']['parts_per_board']} BOM placements per board; "
        f"{facts['centroid_rows']} SMD centroid rows.\n\n"
        "## Evidence boundary\n\n"
        "Dimensions and stack-up thickness come from KiCad board statistics. "
        "Layer names come from the saved board. Component "
        "counts come from the exported BOM and centroid. "
        "Quote selections come only from the export config and "
        "are not vendor-approved by this tool. "
        "Mechanical files are copied only when `mechanical_dir` is configured. "
        "Unknown choices are printed explicitly and keep release on HOLD where required.\n\n"
        "## Release holds\n\n" + blockers + "\n\n"
        "Only `04-Fabrication/*-PCBWay-Gerber.zip` goes into the PCB fabrication upload. "
        "Use the separate BOM, centroid and Assembly Other Files ZIP for PCBA. "
        "The source ZIP and review files are not fabrication uploads.\n",
        encoding="utf-8",
    )
    fab = context.dirs["fab"] / "FABRICATION-AND-STACKUP-SPECIFICATION.md"
    requirements = order.get("impedance_requirements") or []
    impedance_rows = (
        "\n".join(
            f"| {entry.get('net_or_class', missing)} | {entry.get('target_ohms', missing)} | "
            f"{entry.get('signal_layer', missing)} | {entry.get('reference_plane', missing)} | "
            f"{entry.get('width_mm', missing)} | {entry.get('gap_mm', missing)} |"
            for entry in requirements
            if isinstance(entry, dict)
        )
        or f"| {missing} | {missing} | {missing} | {missing} | {missing} | {missing} |"
    )
    fab.write_text(
        f"# {context.prefix} — PCBWay fabrication and stack-up request\n\n"
        "Requested values require PCBWay CAM confirmation. The "
        "board-file stack-up is not a production approval.\n\n"
        "| Parameter | Requested / observed |\n|---|---|\n"
        f"| Board size | {metric('width_mm')} × {metric('height_mm')} |\n"
        f"| Finished size tolerance | {option('board_size_tolerance_mm', ' mm')} |\n"
        f"| PCB type | {option('pcb_type')} |\n"
        f"| Copper layers | {copper} |\n"
        f"| Finished thickness requested | {option('finished_thickness_mm', ' mm')} |\n"
        f"| KiCad stack-up thickness | {metric('stackup_thickness_mm')} |\n"
        f"| PCBWay stack-up ID / approval | "
        f"{option('standard_stackup_id')} / "
        f"{option('stackup_status')} |\n"
        f"| Material / grade | {option('material')} / {option('material_grade')} |\n"
        f"| Outer / inner copper | "
        f"{option('finished_outer_copper_oz', ' oz')} / "
        f"{option('inner_copper_oz', ' oz')} |\n"
        f"| Finish, mask, legend | {option('surface_finish')}; "
        f"{option('solder_mask')}; {option('silkscreen')} |\n"
        f"| Via treatment | {option('via_treatment')} |\n"
        f"| Panelization | {option('panelization')} |\n"
        f"| Electrical test / IPC class | {option('electrical_test_and_ipc_class')} |\n\n"
        "## Controlled impedance schedule\n\n"
        "| Net or class | Target Ω | Signal layer | Reference plane | Width mm | Gap mm |\n"
        "|---|---|---|---|---|---|\n" + impedance_rows + "\n\n"
        f"Requested tolerance: {option('impedance_tolerance_percent', '%')}. "
        "Confirm the final dielectric buildup, Dk, production "
        "width/gap, coupon and measured report in writing.\n\n"
        "## CAM questions\n\n"
        "1. Confirm outline, finished size tolerance, holes, slots, plating and panel drawing.\n"
        "2. Return approved stack-up, layer-by-layer copper and dielectric thicknesses.\n"
        "3. Confirm controlled-impedance geometry and any coupon/report requirement.\n"
        "4. Confirm mask, finish, via treatment and electrical test acceptance.\n\n"
        f"Special notes: {option('special_notes')}\n",
        encoding="utf-8",
    )
    bringup = context.dirs["bringup"] / "BRING-UP-AND-TEST-PLAN.md"
    bringup.write_text(
        f"# {context.prefix} — bring-up and test-plan handoff\n\n"
        "Project-specific limits and procedures must be "
        "supplied by the design owner before testing.\n\n"
        "| Stage | Required project-specific evidence | Status |\n|---|---|---|\n"
        "| Visual inspection | Polarity, pin 1, solder quality, "
        "missing parts, shorts | TO DEFINE |\n"
        "| Unpowered checks | Rail-to-ground resistance and expected ranges | TO DEFINE |\n"
        "| First power | Supply, current limit, power sequence, rail limits | TO DEFINE |\n"
        "| Programming | Firmware image, programming path, expected response | TO DEFINE |\n"
        "| Interfaces | Connector pinout, communications, clocks and test fixtures | TO DEFINE |\n"
        "| Functional test | Acceptance criteria, test record "
        "and serial traceability | TO DEFINE |\n\n"
        "This document is a handoff checklist, not a validated electrical test procedure.\n",
        encoding="utf-8",
    )
    return [path.relative_to(context.output).as_posix() for path in (readme, fab, bringup)]


def export_reference(context: Context) -> None:
    schematic_pdf = context.dirs["schematics"] / f"{context.prefix}-Schematic.pdf"
    context.run(
        "sch",
        "export",
        "pdf",
        "-o",
        str(schematic_pdf),
        str(context.schematic),
    )
    if context.docs and context.docs.exists():
        target = context.dirs["reference"] / "Project-Documents"
        for source in context.docs.rglob("*"):
            if source.is_file():
                destination = target / source.relative_to(context.docs)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)


def export_mechanical(context: Context) -> list[str]:
    copied: list[str] = []
    if context.mechanical and context.mechanical.is_dir():
        for source in context.mechanical.rglob("*"):
            if source.is_file():
                relative = source.relative_to(context.mechanical)
                if relative == Path("README.md"):
                    relative = Path("SUPPLIED-README.md")
                destination = context.dirs["mechanical"] / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied.append(destination.relative_to(context.output).as_posix())
    index = context.dirs["mechanical"] / "README.md"
    index.write_text(
        "# Mechanical handoff\n\n"
        + (
            "Supplied mechanical files copied from the configured `mechanical_dir`:\n\n"
            + "\n".join(f"- `{name}`" for name in copied)
            + "\n\n"
            if copied
            else "No mechanical source directory was configured or supplied. "
            "Check the board and chassis interface separately.\n\n"
        )
        + (
            "Mechanical fit, datums, installed component heights "
            "and chassis clearances require project review.\n"
        ),
        encoding="utf-8",
    )
    return copied


def export_source_archive(context: Context) -> dict[str, Any]:
    target = context.dirs["layout"] / f"{context.prefix}-KiCad-Source.zip"
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(context.project.rglob("*")):
            if not source.is_file() or source.is_relative_to(context.output):
                continue
            relative = source.relative_to(context.project)
            if (
                any(
                    part in SOURCE_SKIP_DIRS or part.endswith("-backups") for part in relative.parts
                )
                or source.suffix.lower() in SOURCE_SKIP_SUFFIXES
                or source.name.startswith(("~", "_autosave"))
            ):
                continue
            if (
                source.suffix.lower() not in SOURCE_ALLOWED_SUFFIXES
                and source.name not in SOURCE_ALLOWED_NAMES
            ):
                continue
            archive.write(source, Path(f"{context.prefix}-KiCad") / relative)
            count += 1
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("KiCad source ZIP integrity check failed")
    return {"archive": target.relative_to(context.output).as_posix(), "files": count}


def export_layout_views(context: Context) -> list[str]:
    if not context.render:
        return []
    outputs: list[Path] = []
    for suffix, extra in (
        (
            "3D",
            [
                "--no-dnp",
                "--include-tracks",
                "--include-pads",
                "--include-zones",
                "--include-silkscreen",
                "--include-soldermask",
            ],
        ),
        ("3D-Fit-Check", ["--no-dnp"]),
        ("3D-Board-Only", ["--board-only"]),
    ):
        output = context.dirs["layout"] / f"{context.prefix}-{suffix}.step"
        context.run(
            "pcb", "export", "step", "--force", *extra, "-o", str(output), str(context.board)
        )
        outputs.append(output)
    for name, side, rotate in (
        ("Top", "top", None),
        ("Bottom", "bottom", None),
        ("Isometric-Top", "top", "-45,0,45"),
        ("Isometric-Bottom", "bottom", "45,0,-45"),
    ):
        output = context.dirs["layout_renders"] / f"{context.prefix}-{name}.png"
        args = [
            "pcb",
            "render",
            "--side",
            side,
            "--quality",
            "high",
            "--background",
            "opaque",
            "--width",
            "2400",
            "--height",
            "1600",
        ]
        if rotate:
            args.extend(["--rotate", rotate, "--perspective", "--zoom", "0.85"])
        context.run(*args, "-o", str(output), str(context.board))
        outputs.append(output)
    return [path.relative_to(context.output).as_posix() for path in outputs]


def write_packing_list(context: Context, bom_rows: list[list[Any]]) -> Path | None:
    if context.pcbway["assembly_mode"] == "turnkey":
        return None
    quantity = int(context.pcbway.get("assembled_quantity") or 0)
    header = [
        "BOM Line",
        "Reference Designator",
        "Manufacturer",
        "Manufacturer Part Number",
        "Required Quantity",
        "Customer Shipped Quantity",
        "Lot / Date Code",
        "Packing Notes",
    ]
    rows = [
        [row[0], row[2], row[7], row[8], int(row[1]) * quantity, "", "", ""]
        for row in bom_rows
        if str(row[10]).casefold() in {"customer", "consigned"}
    ]
    output = context.dirs["assembly"] / f"{context.prefix}-Customer-Parts-Packing-List.xlsx"
    write_xlsx(output, "Packing List", header, rows)
    return output


def package_other_files(context: Context, files: list[Path]) -> Path:
    target = context.dirs["assembly"] / f"{context.prefix}-PCBWay-Assembly-Other-Files.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            if path.exists() and path != target:
                archive.write(path, path.relative_to(context.dirs["assembly"]))
    return target


def write_manifest(context: Context) -> Path:
    output = context.output / "SHA256SUMS.json"
    entries = []
    for path in sorted(context.output.rglob("*")):
        if path.is_file() and path != output:
            entries.append(
                {
                    "path": path.relative_to(context.output).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    output.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--replace-output", action="store_true")
    arguments = parser.parse_args()

    config_path = arguments.config.resolve()
    context = Context(json.loads(config_path.read_text(encoding="utf-8-sig")), config_path)
    context.validate()
    prepare_output(context, arguments.replace_output)

    board_text = context.board.read_text(encoding="utf-8")
    copper = enabled_copper_layers(board_text)
    if context.pcbway.get("layer_count") is not None and len(copper) != int(
        context.pcbway["layer_count"]
    ):
        raise ValueError(
            f"board has {len(copper)} copper layers but config requests "
            f"{context.pcbway['layer_count']}"
        )
    kinds = footprint_kinds(board_text)
    version = context.run("--version").stdout.strip()
    reports = export_reports(context)
    fabrication = export_fabrication(context, gerber_layers(context, copper))
    fabrication_archive_errors = check_fabrication_archive(context, fabrication, copper)
    board_statistics = export_board_statistics(context)
    bom_rows, bom = export_bom(context, kinds)
    centroid_rows = parse_position_rows(context, kinds)
    centroid_refs = {row[0] for row in centroid_rows}
    smd_refs = set(bom["smd_references"])
    parity = {
        "smd_bom_not_in_centroid": sorted(smd_refs - centroid_refs, key=natural),
        "centroid_not_in_bom": sorted(centroid_refs - set(bom["references"]), key=natural),
    }
    assembly_files = export_assembly_documents(context)
    order_spec = write_order_specification(context, copper)
    assembly_files.append(order_spec)
    packing_list = write_packing_list(context, bom_rows)
    if packing_list:
        assembly_files.append(packing_list)
    package_other_files(context, assembly_files)
    export_reference(context)
    mechanical_files = export_mechanical(context)
    source_archive = export_source_archive(context)
    layout_view_error = None
    try:
        layout_views = export_layout_views(context)
    except RuntimeError as error:
        layout_views = [
            path.relative_to(context.output).as_posix()
            for path in context.dirs["layout"].rglob("*")
            if path.is_file() and path.suffix.lower() in {".step", ".png"}
        ]
        layout_view_error = str(error)

    unresolved = []
    unresolved.extend(fabrication_archive_errors)
    if layout_view_error:
        unresolved.append("STEP/3D export failed: " + layout_view_error)
    for key in (
        "pcb_quantity",
        "assembled_quantity",
        "pcb_type",
        "material",
        "finished_thickness_mm",
        "finished_outer_copper_oz",
        "inner_copper_oz",
        "surface_finish",
        "solder_mask",
        "silkscreen",
        "controlled_impedance",
    ):
        if context.pcbway.get(key) is None or context.pcbway.get(key) == "":
            unresolved.append(f"PCBWay order choice not recorded: {key}")
    for key in ("pcb_quantity", "assembled_quantity"):
        value = context.pcbway.get(key)
        if value is not None and (not isinstance(value, int) or value < 1):
            unresolved.append(f"PCBWay {key} must be a positive whole number")
    if (
        context.pcbway.get("controlled_impedance")
        and context.pcbway.get("stackup_status") != "confirmed"
    ):
        unresolved.append(
            "controlled impedance is enabled but the PCBWay stack-up is not confirmed"
        )
    if context.pcbway.get("standard_stackup_id") is None:
        unresolved.append("PCBWay standard stack-up ID is not selected")
    if context.pcbway.get("inner_residual_copper_percent") is None:
        unresolved.append("inner-layer residual copper ratio is not measured/confirmed")
    if bom["missing_mpn"]:
        unresolved.append("PCBWay-sourced BOM lines are missing MPNs")
    if bom["missing_manufacturer"]:
        unresolved.append("PCBWay-sourced BOM lines are missing manufacturers")
    if parity["smd_bom_not_in_centroid"] or parity["centroid_not_in_bom"]:
        unresolved.append("BOM/centroid parity is not clean")
    if bom["duplicate_references"]:
        unresolved.append("duplicate BOM references: " + ", ".join(bom["duplicate_references"]))
    if len(bom["smd_references"]) + len(bom["tht_references"]) != bom["parts_per_board"]:
        unresolved.append("some assembled BOM parts have unknown or hybrid mounting type")
    for name in ("erc", "drc"):
        report = reports[name]
        if not report["exists"] or report["return_code"] != 0 or report["findings_detected"]:
            unresolved.append(f"{name.upper()} report has findings, failed, or is missing")
    if board_statistics["width_mm"] is None or board_statistics["height_mm"] is None:
        unresolved.append("board dimensions could not be read from KiCad statistics")
    board_job = fabrication.get("gerber_job_general", {})
    if (
        context.pcbway.get("finished_thickness_mm") is not None
        and board_job.get("BoardThickness") is not None
    ):
        if (
            abs(float(context.pcbway["finished_thickness_mm"]) - float(board_job["BoardThickness"]))
            > 0.05
        ):
            unresolved.append("requested thickness differs from KiCad Gerber job board thickness")
    if context.pcbway.get("surface_finish") and board_job.get("Finish"):
        if str(context.pcbway["surface_finish"]).casefold() != str(board_job["Finish"]).casefold():
            unresolved.append("requested surface finish differs from KiCad Gerber job finish")
    if (
        context.pcbway.get("controlled_impedance") is not None
        and board_job.get("ImpedanceControlled") is not None
    ):
        if bool(context.pcbway["controlled_impedance"]) != bool(board_job["ImpedanceControlled"]):
            unresolved.append("controlled-impedance choice differs from KiCad Gerber job")

    facts = {
        "generated": date.today().isoformat(),
        "kicad_version": version,
        "manufacturer": "PCBWay",
        "source_urls": SOURCE_URLS,
        "board": context.board.name,
        "board_statistics": board_statistics,
        "copper_layers": copper,
        "origin": "auxiliary/drill origin" if context.use_origin else "absolute KiCad origin",
        "reports": reports,
        "fabrication": fabrication,
        "fabrication_archive_errors": fabrication_archive_errors,
        "bom": bom,
        "centroid_rows": len(centroid_rows),
        "centroid_sides": sorted({row[6] for row in centroid_rows}),
        "parity": parity,
        "order": context.pcbway,
        "source_archive": source_archive,
        "layout_views": layout_views,
        "layout_view_error": layout_view_error,
        "mechanical_files": mechanical_files,
        "unresolved_release_items": unresolved,
    }
    guide = write_order_guide(context, facts)
    facts["order_guide"] = guide.relative_to(context.output).as_posix()
    facts["package_documents"] = write_package_documents(context, facts)
    context.facts.parent.mkdir(parents=True, exist_ok=True)
    context.facts.write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    write_manifest(context)
    print(json.dumps({"output": str(context.output), **facts}, indent=2))
    return 0 if not unresolved else 2


if __name__ == "__main__":
    raise SystemExit(main())
