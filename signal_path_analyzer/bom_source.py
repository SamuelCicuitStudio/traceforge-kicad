"""Fresh saved-schematic BOM extraction, separate from a partial PCB placement."""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_netlist(path):
    root = ET.parse(path).getroot()
    parts = []
    for comp in root.findall("./components/comp"):
        properties = {f.get("name", ""): f.text or "" for f in comp.findall("./fields/field")}
        flags = {p.get("name", ""): p.get("value", "") for p in comp.findall("property")}
        for key, value in flags.items():
            if value:
                if not properties.get(key):
                    properties[key] = value

        def marked(name, flags=flags):
            return name in flags and str(flags[name]).lower() not in ("false", "no", "0")

        properties.setdefault("Datasheet", comp.findtext("datasheet", ""))
        properties.setdefault("Description", comp.findtext("description", ""))
        parts.append(
            dict(
                reference=comp.get("ref", ""),
                value=comp.findtext("value", ""),
                footprint=comp.findtext("footprint", ""),
                properties=properties,
                dnp=marked("dnp"),
                exclude_bom=marked("exclude_from_bom"),
            )
        )
    return parts


def saved_schematic(schematic, worker, cli):
    schematic = Path(schematic).resolve()
    if not schematic.is_file() or schematic.suffix != ".kicad_sch":
        raise ValueError("Choose the saved root schematic for the full BOM")
    with tempfile.TemporaryDirectory(prefix="traceforge-bom-") as temp:
        output = Path(temp) / "bom.xml"
        worker.run(
            [
                cli,
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadxml",
                "--output",
                str(output),
                str(schematic),
            ]
        )
        return dict(
            source="saved root schematic (unsaved schematic edits excluded)",
            schematic=str(schematic),
            parts=parse_netlist(output),
        )
