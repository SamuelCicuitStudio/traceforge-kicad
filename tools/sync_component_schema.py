"""Synchronize the canonical PCB skill component contract into offline consumers."""

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT.parent / "pcb/assets/component-schema.json"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=DEFAULT)
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    source = args.source.read_bytes().replace(b"\r\n", b"\n")
    destinations = [
        ROOT / "signal_path_analyzer/component_schema.json",
        ROOT.parent.parent / "TraceForgerouter/schematic-authoring/templates/component-schema.json",
    ]
    # The sibling TraceForgerouter checkout is independent of plugin installation.
    destinations[1] = (
        ROOT.parent.parent / "TraceForgerouter/schematic-authoring/templates/component-schema.json"
    )
    for path in destinations:
        if args.check:
            if not path.is_file() or path.read_bytes().replace(b"\r\n", b"\n") != source:
                raise SystemExit("Component contract differs: " + str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source)
    print("Component contract SHA256 " + hashlib.sha256(source).hexdigest())


if __name__ == "__main__":
    main()
