"""Choose the manufacturer-specific KiCad manufacturing package exporter."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTERS = {
    "pcbpower": ROOT / "skills/kicad-pcb-power/scripts/export_package.py",
    "pcbway": ROOT / "skills/kicad-pcbway/scripts/export_package.py",
}


def package_paths(manufacturer: str, config_path: Path) -> tuple[Path, Path]:
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if manufacturer == "pcbway" and not isinstance(config.get("pcbway"), dict):
        raise ValueError("PCBWay requires a PCBWay export config with a 'pcbway' section")
    if manufacturer == "pcbpower" and "pcbway" in config:
        raise ValueError("PCBPower requires a PCBPower export config, not a PCBWay config")
    project = (config_path.parent / config["project_dir"]).resolve()
    output = (config_path.parent / config["output_dir"]).resolve()
    if (
        output == Path(output.anchor)
        or output == project
        or project.is_relative_to(output)
        or output.is_relative_to(project)
    ):
        raise ValueError(f"unsafe output directory: {output}")
    return project, output


def run_board(manufacturer: str, config: Path, replace: bool) -> int:
    _, output = package_paths(manufacturer, config)
    if manufacturer == "pcbpower" and output.exists():
        marker = output / "EXPORT-FACTS.json"
        if not replace:
            raise FileExistsError(
                f"PCBPower output already exists; pass --replace-output after review: {output}"
            )
        if not marker.is_file():
            raise ValueError(
                f"refusing to replace a folder without PCBPower package marker: {output}"
            )
    command = [sys.executable, str(EXPORTERS[manufacturer]), "--config", str(config)]
    if manufacturer == "pcbway" and replace:
        command.append("--replace-output")
    print(f"Manufacturer: {manufacturer}\nDeliverable folder: {output}", flush=True)
    return subprocess.run(command, check=False).returncode


def bundle_paths(manufacturer: str, manifest_path: Path) -> tuple[Path, list[tuple[Path, Path]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    root = (manifest_path.parent / manifest["bundle_output_dir"]).resolve()
    if root == Path(root.anchor):
        raise ValueError("bundle output cannot be a drive root")
    configs = manifest.get("board_configs")
    if not isinstance(configs, list) or not configs:
        raise ValueError("manifest.board_configs must list one or more board configs")
    selected = []
    for item in configs:
        config = (manifest_path.parent / item).resolve()
        project, output = package_paths(manufacturer, config)
        if output.parent != root or root == project or project.is_relative_to(root):
            raise ValueError(
                f"each board output must be a direct child of the bundle root: {output}"
            )
        selected.append((config, output))
    if len({output for _, output in selected}) != len(selected):
        raise ValueError("board output directories must be distinct")
    return root, selected


def run_bundle(manufacturer: str, manifest_path: Path, replace: bool) -> int:
    root, selected = bundle_paths(manufacturer, manifest_path)
    marker = root / "BUNDLE-FACTS.json"
    if root.exists() and (not replace or not marker.is_file()):
        raise ValueError(
            f"existing bundle requires --replace-output and its BUNDLE-FACTS.json marker: {root}"
        )
    root.mkdir(parents=True, exist_ok=True)
    records = []
    marker.write_text(
        json.dumps({"manufacturer": manufacturer, "boards": []}, indent=2) + "\n", encoding="utf-8"
    )
    for config, output in selected:
        code = run_board(manufacturer, config, replace)
        board_name = json.loads(config.read_text(encoding="utf-8-sig"))["name"]
        facts_path = output / "EXPORT-FACTS.json"
        facts = json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.is_file() else {}
        hold = bool(facts.get("unresolved_release_items")) or bool(
            facts.get("package_preflight", {}).get("errors")
        )
        reports = facts.get("reports", {})
        hold = hold or any(
            report.get("errors", report.get("errors_detected", 0)) for report in reports.values()
        )
        status = "HOLD" if code or hold else "EXPORT CHECKS PASSED — CAM APPROVAL PENDING"
        records.append(
            {
                "config": str(config),
                "folder": output.name,
                "board": board_name,
                "status": status,
                "exit_code": code,
            }
        )
        marker.write_text(
            json.dumps({"manufacturer": manufacturer, "boards": records}, indent=2) + "\n",
            encoding="utf-8",
        )
    rows = "\n".join(
        (
            f"| {item['board'] or 'UNKNOWN'} | "
            f"[{item['folder']}]({item['folder']}/) | "
            f"{item['status']} |"
        )
        for item in records
    )
    (root / "README.md").write_text(
        f"# {manufacturer.upper()} board deliverables\n\n"
        "Each board folder contains its own source archive, "
        "fabrication files, assembly files, reports, "
        "ordering guide and checksums. Review each `EXPORT-FACTS.json` and release holds.\n\n"
        "| Board | Package | Export state |\n|---|---|---|\n" + rows + "\n\n"
        "A generated package is not vendor CAM or assembly approval.\n",
        encoding="utf-8",
    )
    return 0 if all(item["exit_code"] == 0 for item in records) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manufacturer", required=True, choices=tuple(EXPORTERS))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path)
    source.add_argument("--manifest", type=Path)
    parser.add_argument("--replace-output", action="store_true")
    args = parser.parse_args()
    if args.manifest:
        return run_bundle(args.manufacturer, args.manifest.resolve(), args.replace_output)
    return run_board(args.manufacturer, args.config.resolve(), args.replace_output)


if __name__ == "__main__":
    raise SystemExit(main())
