"""Copy the reviewed deterministic vendor exporters into the TraceForge runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "signal_path_analyzer" / "manufacturing_resources"
SOURCES = {
    "scripts/export_manufacturing.py": "scripts/export_manufacturing.py",
    "skills/kicad-pcb-power/scripts/export_package.py": "skills/kicad-pcb-power/scripts/export_package.py",  # noqa: E501 - composed report text or resource path
    "skills/kicad-pcb-power/scripts/package_preflight.py": "skills/kicad-pcb-power/scripts/package_preflight.py",  # noqa: E501 - composed report text or resource path
    "skills/kicad-pcbway/scripts/export_package.py": "skills/kicad-pcbway/scripts/export_package.py",  # noqa: E501 - composed report text or resource path
}


def sync(source_root: Path) -> dict[str, str]:
    versions = {}
    for relative_source, relative_destination in SOURCES.items():
        source = source_root / relative_source
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = DESTINATION / relative_destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        versions[relative_destination] = hashlib.sha256(destination.read_bytes()).hexdigest()
    (DESTINATION / "SOURCE-MANIFEST.json").write_text(
        json.dumps(
            {"source": "pcb skill deterministic exporter scripts", "sha256": versions}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return versions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcb-skill-root", type=Path, default=ROOT.parent / "pcb")
    args = parser.parse_args()
    versions = sync(args.pcb_skill_root.resolve())
    print(f"Synchronized {len(versions)} exporter files into {DESTINATION}")


if __name__ == "__main__":
    main()
