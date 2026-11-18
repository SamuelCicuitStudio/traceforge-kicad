"""Register the supported KiCad 10 schematic launcher without changing other preferences."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

NAME = "TraceForge Components (LCSC)"


def register(config, plugin, python):
    config, plugin, python = Path(config), Path(plugin), Path(python)
    script = plugin / "traceforge_components.py"
    if not script.is_file() or not python.is_file():
        raise ValueError("Installed TraceForge component entry point and KiCad Python are required")
    data = json.loads(config.read_text(encoding="utf-8-sig"))
    before = json.loads(json.dumps(data))
    entry = dict(
        name=NAME, path=str(script), command=f'"{python}" "{script}" --from-netlist "%I" --launch'
    )
    plugins = data.setdefault("bom", {}).setdefault("plugins", [])
    old = next((p for p in plugins if p.get("name") == NAME), None)
    if old:
        old.update(entry)
    else:
        plugins.append(entry)
    if data == before:
        return False
    backup = config.with_name(
        config.name + ".traceforge-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".bak"
    )
    shutil.copy2(config, backup)
    temp = config.with_suffix(".traceforge.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, config)
    print("Registered schematic launcher; preferences backup:", backup)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plugin", type=Path, required=True)
    p.add_argument("--python", type=Path, default=Path(sys.executable))
    p.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("APPDATA", Path.home())) / "kicad/10.0/eeschema.json",
    )
    a = p.parse_args()
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq eeschema.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=True,
        )
        if any(
            row and row[0].casefold() == "eeschema.exe"
            for row in csv.reader(io.StringIO(result.stdout))
        ):
            raise SystemExit(
                "Save and close Schematic Editor before registering its launcher; "
                "its live preferences could overwrite this change."
            )
    register(a.config, a.plugin, a.python)


if __name__ == "__main__":
    main()
