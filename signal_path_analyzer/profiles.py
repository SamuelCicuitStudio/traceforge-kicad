"""KiCad 10 tuning profiles and stackup heights, read from the project and board files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

IU_PER_PS = 1_000_000  # KiCad stores time in attoseconds


@dataclass(frozen=True)
class TuningProfile:
    """Per-layer unit delay (ps/mm) and via unit delay (ps/mm of stack height)."""

    name: str
    layer_ps_per_mm: dict[str, float]
    via_ps_per_mm: float

    def track_delay(self, layer: str, length_mm: float) -> Optional[float]:
        unit = self.layer_ps_per_mm.get(layer)
        return None if unit is None else unit * length_mm


@dataclass
class ProjectTiming:
    profiles: dict[str, TuningProfile] = field(default_factory=dict)
    netclass_profile: dict[str, str] = field(default_factory=dict)

    def profile_for_netclass(self, netclass: Optional[str]) -> Optional[TuningProfile]:
        name = self.netclass_profile.get(netclass or "")
        return self.profiles.get(name) if name else None


def load_project_timing(project_file: Path) -> ProjectTiming:
    """Read tuning profiles and netclass assignments from a .kicad_pro file."""

    data = json.loads(Path(project_file).read_text(encoding="utf-8"))
    timing = ProjectTiming()
    for entry in data.get("tuning_profiles", {}).get("tuning_profiles_impedance_geometric", []):
        layers = {
            row["signal_layer"]: row["delay"] / IU_PER_PS
            for row in entry.get("layer_entries", [])
            if row.get("delay")
        }
        timing.profiles[entry["profile_name"]] = TuningProfile(
            name=entry["profile_name"],
            layer_ps_per_mm=layers,
            via_ps_per_mm=entry.get("via_prop_delay", 0) / IU_PER_PS,
        )
    for netclass in data.get("net_settings", {}).get("classes", []):
        if netclass.get("tuning_profile"):
            timing.netclass_profile[netclass["name"]] = netclass["tuning_profile"]
    return timing


_LAYER = re.compile(r'\(layer "([^"]+)"(.*?)\n\t\t\t\)', re.S)
_THICK = re.compile(r"\(thickness ([\d.]+)")


def load_stackup_z(board_file: Path) -> dict[str, tuple[float, float]]:
    """Return (top, bottom) z in mm, measured from the top of the stackup, for each copper layer."""

    text = Path(board_file).read_text(encoding="utf-8")
    start = text.find("(stackup")
    if start < 0:
        return {}
    z = 0.0
    out: dict[str, tuple[float, float]] = {}
    for match in _LAYER.finditer(text, start):
        name, body = match.group(1), match.group(2)
        thickness = _THICK.search(body)
        t = float(thickness.group(1)) if thickness else 0.0
        if name.endswith(".Cu"):
            out[name] = (z, z + t)
        if name == "B.Cu":
            break
        z += t
    return out


def via_height(z: dict[str, tuple[float, float]], layer_a: str, layer_b: str) -> float:
    """KiCad's default via length: top of the upper copper layer to the bottom of the lower one.

    Reference calculation: a through via (F.Cu-B.Cu, 1.636 mm) reports
    11.374 ps at 6.952 ps/mm.
    """

    if layer_a not in z or layer_b not in z:
        return 0.0
    return max(z[layer_a][1], z[layer_b][1]) - min(z[layer_a][0], z[layer_b][0])
