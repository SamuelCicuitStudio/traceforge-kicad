"""Offline Signal Chain builder: create <board>.traceforge.json without KiCad running.

Usage (KiCad's Python, for pcbnew positions):
  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" tools/build_chains.py PROJECT_DIR \\
      --parts U4 U6 U7 U8 U9 --to J2 J3 J5 J6 U1 [--ohms 100] [--caps] [--dry-run]

Every --parts component is tried as a driver towards every other --parts/--to component. The netlist
comes from kicad-cli, positions from the board (driver side = endpoint nearest the series part),
netclasses from the project's netclass patterns. Timed netclasses are those with a tuning profile;
if the project has none, every netclass except Default/PWR*/FINE* counts as timed.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as E
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_path_analyzer.chains import board_config_path, config_to_json  # noqa: E402
from signal_path_analyzer.pathfinder import (  # noqa: E402
    dedupe,
    find_chains,
    mark_untimed,
    merge_into,
    name_and_group,
    orient_by_placement,
    suggest_groups,
)

CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"


def netlist_parts(sch: Path) -> list:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "n.xml"
        subprocess.run([CLI, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out),
                        str(sch)], check=True, capture_output=True)
        root = E.parse(out).getroot()
    value = {c.get("ref"): c.findtext("value") for c in root.findall(".//components/comp")}
    dnp = {c.get("ref") for c in root.findall(".//components/comp")
           if any(p.get("name") == "dnp" for p in c.findall("property"))}
    pads: dict[str, dict[str, str]] = defaultdict(dict)
    for n in root.findall(".//nets/net"):
        for node in n.findall("node"):
            pads[node.get("ref")][node.get("pin")] = n.get("name")
    return [(r, value.get(r, ""), p) for r, p in pads.items() if r not in dnp]


def board_positions(pcb: Path):
    import pcbnew

    b = pcbnew.LoadBoard(str(pcb))
    pads, parts = {}, {}
    for f in b.GetFootprints():
        ref = f.GetReference()
        parts[ref] = tuple(v / 1e6 for v in f.GetPosition())
        for p in f.Pads():
            pads[f"{ref}.{p.GetNumber()}"] = tuple(v / 1e6 for v in p.GetPosition())
    return pads, parts


def netclass_lookup(pro: Path):
    data = json.loads(pro.read_text(encoding="utf-8"))
    pats = data["net_settings"].get("netclass_patterns") or []
    timed = {c["name"] for c in data["net_settings"]["classes"] if c.get("tuning_profile")}
    if not timed:
        timed = {c["name"] for c in data["net_settings"]["classes"]
                 if c["name"] != "Default" and not c["name"].startswith(("PWR", "FINE"))}

    def of(net: str):
        return next((p["netclass"] for p in pats if fnmatch.fnmatchcase(net, p["pattern"])),
                    "Default")

    return of, timed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--parts", nargs="+", required=True, help="ICs that drive and receive")
    ap.add_argument("--to", nargs="*", default=[], help="receive-only parts (connectors, flash)")
    ap.add_argument("--ohms", type=float, default=100.0)
    ap.add_argument("--caps", action="store_true", help="also pass AC-coupling capacitors")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    pro = next(a.project.glob("*.kicad_pro"))
    sch, pcb = pro.with_suffix(".kicad_sch"), pro.with_suffix(".kicad_pcb")
    parts = netlist_parts(sch)
    found = []
    for src in a.parts:
        others = [p for p in a.parts + a.to if p != src]
        found += find_chains(parts, [src], others, a.ohms, a.caps)
    pads, part_xy = board_positions(pcb)
    flipped = orient_by_placement(found, pads, part_xy)
    found = dedupe(found)
    of, timed = netclass_lookup(pro)
    mark_untimed(found, {n: of(n) for c in found for n in c.nets}, timed)
    name_and_group(found)
    kept = [c for c in found if c.keep]
    groups = suggest_groups(kept)
    for g in groups:
        print(f"{g.name:22} {len(g.chains):3} chains  skew={g.skew_ps} pair={g.pair_skew_ps} "
              f"stub={g.stub_max_ps}  e.g. {g.chains[0].name} {g.chains[0].series}")
    print(f"{len(found)} chains found ({len(found) - len(kept)} untimed skipped), "
          f"{flipped} reoriented by placement, {len(groups)} groups")
    if not a.dry_run:
        out = board_config_path(pcb)
        out.write_text(config_to_json(merge_into(None, groups)), encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
