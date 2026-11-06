"""Deterministic, file-based manufacturing inventory, checks and export orchestration.

No pcbnew object is accessed here. The caller must save the project before running
KiCad CLI exports. Vendor exporters are shipped with TraceForge and run in a separate
Python with openpyxl available; no installed SKILL repository is needed at runtime.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESOURCES = Path(__file__).resolve().parent / "manufacturing_resources"
WRAPPER = RESOURCES / "scripts" / "export_manufacturing.py"
SOURCE_EXTENSIONS = {
    ".kicad_pcb",
    ".kicad_sch",
    ".kicad_pro",
    ".kicad_dru",
    ".kicad_sym",
    ".kicad_mod",
    ".step",
    ".stp",
    ".wrl",
}
TABLE_FILES = ("sym-lib-table", "fp-lib-table")
QUOTE_FIELDS = (
    "assembly_mode",
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
)
PCBWAY_EDIT_FIELDS = (
    *QUOTE_FIELDS,
    "standard_stackup_id",
    "stackup_status",
    "inner_residual_copper_percent",
    "special_notes",
)


def verify_bundled_exporters() -> dict[str, str]:
    manifest_path = RESOURCES / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = manifest["sha256"]
    if not hashes:
        raise ValueError("Bundled exporter manifest is empty")
    for name, expected in hashes.items():
        path = (RESOURCES / name).resolve()
        if (
            not path.is_relative_to(RESOURCES.resolve())
            or not path.is_file()
            or digest(path) != expected
        ):
            raise ValueError(f"Bundled exporter failed integrity check: {name}")
    return hashes


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _form_end(text: str, start: int) -> int:
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
        elif char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("Unbalanced KiCad library table")


def _table_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8-sig")
    entries = []
    for match in re.finditer(r"\(lib\s+", text):
        end = _form_end(text, match.start())
        form = text[match.start() : end]
        name = re.search(r'\(name\s+"((?:\\.|[^"\\])*)"\)', form)
        uri = re.search(r'\(uri\s+"((?:\\.|[^"\\])*)"\)', form)
        if name:
            entries.append(
                {
                    "name": name.group(1),
                    "uri": uri.group(1) if uri else "",
                    "start": match.start(),
                    "end": end,
                    "form": form,
                }
            )
    return entries


def _resolved_local_uri(uri: str, project: Path) -> Path | None:
    value = uri.replace("${KIPRJMOD}", str(project)).replace("$(KIPRJMOD)", str(project))
    if "${" in value or "$(" in value or "://" in value:
        return None
    path = Path(value)
    return (project / path).resolve() if not path.is_absolute() else path.resolve()


def _schematic_files(root: Path) -> tuple[list[Path], list[str]]:
    pending = [root]
    visited: set[Path] = set()
    missing = []
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        if not path.is_file():
            missing.append(str(path))
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for name in re.findall(r'\(property\s+"Sheetfile"\s+"([^"\r\n]+)"', text):
            pending.append((path.parent / name).resolve())
    return sorted(visited), sorted(missing)


def project_inventory(board_file: Path) -> dict[str, Any]:
    board = board_file.resolve()
    if not board.is_file() or board.suffix != ".kicad_pcb":
        raise FileNotFoundError(f"Saved KiCad board required: {board}")
    project = board.parent
    schematic = board.with_suffix(".kicad_sch")
    project_settings = board.with_suffix(".kicad_pro")
    sheets, missing_sheets = _schematic_files(schematic)
    existing_sheets = [path for path in sheets if path.is_file()]
    schematic_text = "\n".join(
        path.read_text(encoding="utf-8-sig", errors="replace") for path in existing_sheets
    )
    symbol_ids = set(re.findall(r'\(lib_id\s+"([^":]+):[^"\r\n]+"\)', schematic_text))
    footprint_ids = set(
        re.findall(r'\(property\s+"Footprint"\s+"([^":]+):[^"\r\n]+"', schematic_text)
    )
    board_text = board.read_text(encoding="utf-8-sig", errors="replace")
    footprint_ids.update(re.findall(r'\(footprint\s+"([^":]+):[^"\r\n]+"', board_text))
    copper = (
        re.findall(
            r'\(\d+\s+"([^"\r\n]+\.Cu)"\s+(?:signal|power|mixed|jumper)',
            board_text.split("(layers", 1)[1].split("(setup", 1)[0],
        )
        if "(layers" in board_text
        else []
    )
    source_files = [board, *existing_sheets]
    if project_settings.is_file():
        source_files.append(project_settings)
    rules = board.with_suffix(".kicad_dru")
    if rules.is_file():
        source_files.append(rules)
    libraries = []
    issues = [
        {"severity": "error", "kind": "missing_sheet", "path": path} for path in missing_sheets
    ]
    for table_name, used in (("sym-lib-table", symbol_ids), ("fp-lib-table", footprint_ids)):
        table = project / table_name
        if table.is_file():
            source_files.append(table)
        entries = _table_entries(table)
        seen = set()
        for entry in entries:
            name = entry["name"]
            resolved = _resolved_local_uri(entry["uri"], project)
            record = {
                "table": table_name,
                "name": name,
                "uri": entry["uri"],
                "used": name in used,
                "path": str(resolved) if resolved else None,
                "path_exists": resolved.exists() if resolved else None,
            }
            libraries.append(record)
            if resolved is not None and resolved.exists() and resolved.is_relative_to(project):
                source_files.extend(
                    path
                    for path in (resolved.rglob("*") if resolved.is_dir() else [resolved])
                    if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS
                )
            if name in seen:
                issues.append(
                    {
                        "severity": "error",
                        "kind": "duplicate_library_name",
                        "path": str(table),
                        "name": name,
                    }
                )
            seen.add(name)
            if resolved is not None and not resolved.exists():
                issues.append(
                    {
                        "severity": "warning",
                        "kind": "missing_library_path",
                        "path": str(resolved),
                        "name": name,
                    }
                )
        for name in sorted(used - {entry["name"] for entry in entries}):
            # A global KiCad library may supply this nickname, so it is not a broken link.
            issues.append(
                {
                    "severity": "info",
                    "kind": "external_library_unverified",
                    "path": str(table),
                    "name": name,
                }
            )
    hashes = {str(path.relative_to(project)): digest(path) for path in sorted(set(source_files))}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "board": str(board),
        "project": str(project),
        "schematic": str(schematic),
        "project_settings": str(project_settings),
        "sheets": [str(path) for path in existing_sheets],
        "copper_layers": copper,
        "libraries": libraries,
        "issues": issues,
        "source_hashes": hashes,
        "fingerprint": fingerprint,
    }


def library_cleanup_candidates(inventory: dict[str, Any]) -> list[dict[str, str]]:
    """Offer only project-local, unused table entries; never touch global tables."""
    return [
        {"table": item["table"], "name": item["name"], "uri": item["uri"]}
        for item in inventory["libraries"]
        if not item["used"]
    ]


def apply_library_cleanup(
    board_file: Path, table_name: str, names: list[str], expected_sha256: str
) -> Path:
    if table_name not in TABLE_FILES or not names:
        raise ValueError("Select project-local table entries to remove")
    inventory = project_inventory(board_file)
    project = Path(inventory["project"])
    table = project / table_name
    if not table.is_file() or table.is_symlink() or digest(table) != expected_sha256:
        raise ValueError("Library table changed since preview")
    entries = _table_entries(table)
    selected = [entry for entry in entries if entry["name"] in set(names)]
    if len(selected) != len(names) or len(set(names)) != len(names):
        raise ValueError("Each selected library name must occur exactly once")
    used = {
        item["name"]
        for item in inventory["libraries"]
        if item["table"] == table_name and item["used"]
    }
    if used.intersection(names):
        raise ValueError("Refusing to remove a library used by the current schematic")
    original = table.read_text(encoding="utf-8-sig")
    backup = (
        project
        / f"{table_name}.traceforge-backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"  # noqa: E501 - composed report text or resource path
    )
    backup.write_bytes(table.read_bytes())
    modified = original
    for entry in sorted(selected, key=lambda item: item["start"], reverse=True):
        modified = modified[: entry["start"]] + modified[entry["end"] :]
    first = modified.find("(")
    if first < 0 or _form_end(modified, first) != len(modified.rstrip()):
        raise ValueError("Refusing malformed library table edit; backup retained")
    temporary = table.with_name(table.name + ".traceforge.tmp")
    temporary.write_text(modified, encoding="utf-8")
    temporary.replace(table)
    return backup


def quote_unknowns(manufacturer: str, config: dict[str, Any]) -> list[str]:
    if manufacturer == "pcbway":
        order = config.get("pcbway", {})
        unknown = [
            field for field in QUOTE_FIELDS if order.get(field) is None or order.get(field) == ""
        ]
        unknown.extend(
            field
            for field in ("standard_stackup_id", "inner_residual_copper_percent")
            if order.get(field) is None or order.get(field) == ""
        )
        if order.get("controlled_impedance") and order.get("stackup_status") != "confirmed":
            unknown.append("confirmed_stackup")
        return unknown
    if manufacturer == "pcbpower":
        return []  # Optional; the exporter checks actual CAM attachments after generation.
    raise ValueError("manufacturer must be pcbpower or pcbway")


def load_config(config_path: Path) -> dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8-sig"))


def save_reviewed_config(path: Path, text: str, expected_sha256: str, manufacturer: str) -> Path:
    """Save a manually edited vendor config, preserving its exact prior bytes."""
    path = path.resolve()
    if not path.is_file() or digest(path) != expected_sha256:
        raise ValueError("Configuration changed since opening the editor")
    config = json.loads(text)
    if not isinstance(config, dict) or not all(
        config.get(key) for key in ("project_dir", "name", "output_dir", "kicad_cli")
    ):
        raise ValueError("Config needs project_dir, name, output_dir and kicad_cli")
    if manufacturer == "pcbway" and not isinstance(config.get("pcbway"), dict):
        raise ValueError("PCBWay configuration needs a pcbway object")
    if manufacturer == "pcbway" and config["pcbway"].get("assembly_mode") not in (
        None,
        "turnkey",
        "partial_turnkey",
        "consigned",
    ):
        raise ValueError("PCBWay assembly_mode must be turnkey, partial_turnkey or consigned")
    if manufacturer == "pcbpower" and "pcbway" in config:
        raise ValueError("PCBPower configuration cannot contain pcbway settings")
    project = (path.parent / config["project_dir"]).resolve()
    output = _output(path, config)
    if (
        output == project
        or project.is_relative_to(output)
        or output.is_relative_to(project)
        or output == Path(output.anchor)
    ):
        raise ValueError("Output directory must stay outside the source project")
    backup = path.with_name(path.name + f".traceforge-backup-{uuid.uuid4().hex[:8]}")
    backup.write_bytes(path.read_bytes())
    temporary = path.with_name(path.name + ".traceforge.tmp")
    temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return backup


def save_engineering_choices(
    path: Path, manufacturer: str, values: dict[str, str], expected_sha256: str
) -> Path:
    """Update only named user-facing choices; never rewrite design-derived facts."""
    config = load_config(path)
    if manufacturer == "pcbway":
        if not isinstance(config.get("pcbway"), dict) or set(values) != set(PCBWAY_EDIT_FIELDS):
            raise ValueError("PCBWay choice set is incomplete")
        for field, raw in values.items():
            value = raw.strip()
            if not value:
                parsed: Any = None
            elif field in ("pcb_quantity", "assembled_quantity"):
                parsed = int(value)
                if parsed < 1:
                    raise ValueError(f"{field} must be a positive whole number")
            elif field in (
                "finished_thickness_mm",
                "finished_outer_copper_oz",
                "inner_copper_oz",
                "inner_residual_copper_percent",
            ):
                parsed = float(value)
                if (
                    not math.isfinite(parsed)
                    or parsed <= 0
                    or (field == "inner_residual_copper_percent" and parsed > 100)
                ):
                    raise ValueError(f"{field} must be positive and within its valid range")
            elif field == "controlled_impedance":
                if value not in ("Yes", "No"):
                    raise ValueError("Controlled impedance must be Yes, No, or unselected")
                parsed = value == "Yes"
            elif field == "stackup_status":
                if value != "Confirmed by PCBWay":
                    raise ValueError("Stackup status must be confirmed or unselected")
                parsed = "confirmed"
            else:
                parsed = value
            config["pcbway"][field] = parsed
    elif manufacturer == "pcbpower":
        if set(values) != {"docs_dir", "mechanical_dir"}:
            raise ValueError("PCBPower choice set is incomplete")
        for key, label in (
            ("docs_dir", "CAM and ordering notes"),
            ("mechanical_dir", "Mechanical files"),
        ):
            value = values[key].strip()
            folder = (path.parent / value).resolve() if value else None
            if folder and not folder.is_dir():
                raise ValueError(f"{label} folder does not exist")
            config[key] = os.path.relpath(folder, path.parent) if folder else None
    else:
        raise ValueError("Unknown manufacturer")
    return save_reviewed_config(path, json.dumps(config), expected_sha256, manufacturer)


def _output(config_path: Path, config: dict[str, Any]) -> Path:
    return (config_path.parent / config["output_dir"]).resolve()


def output_state(output: Path) -> dict[str, Any]:
    if not output.exists():
        return {
            "exists": False,
            "managed": False,
            "extra_files": [],
            "missing_files": [],
            "changed_files": [],
        }
    manifest = output / "SHA256SUMS.json"
    if manifest.is_file():
        expected = {
            item["path"]: item["sha256"]
            for item in json.loads(manifest.read_text(encoding="utf-8"))
        }
    else:
        manifest = output / "SHA256SUMS.txt"
        if manifest.is_file():
            expected = {
                line.split("  ", 1)[1]: line.split("  ", 1)[0]
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if "  " in line
            }
        else:
            expected = {}
    actual = {
        path.relative_to(output).as_posix(): path for path in output.rglob("*") if path.is_file()
    }
    exclusions = {"SHA256SUMS.json", "SHA256SUMS.txt"}
    return {
        "exists": True,
        "managed": bool(expected),
        "extra_files": sorted(set(actual) - set(expected) - exclusions),
        "missing_files": sorted(set(expected) - set(actual)),
        "changed_files": sorted(
            name for name in set(expected) & set(actual) if digest(actual[name]) != expected[name]
        ),
    }


def preview_package(manufacturer: str, config_path: Path) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = load_config(config_path)
    project = (config_path.parent / config["project_dir"]).resolve()
    board = project / f"{config['name']}.kicad_pcb"
    inventory = project_inventory(board)
    output = _output(config_path, config)
    if (
        output == project
        or project.is_relative_to(output)
        or output.is_relative_to(project)
        or output == Path(output.anchor)
    ):
        raise ValueError("Output directory must stay outside the source project")
    if manufacturer == "pcbway" and not isinstance(config.get("pcbway"), dict):
        raise ValueError("PCBWay config requires a pcbway section")
    if manufacturer == "pcbpower" and "pcbway" in config:
        raise ValueError("PCBPower config cannot contain a pcbway section")
    supporting_hashes = {}
    supporting_issues = []
    for key in ("docs_dir", "mechanical_dir"):
        value = config.get(key)
        if not value:
            continue
        source = (config_path.parent / value).resolve()
        if source == output or source.is_relative_to(output):
            raise ValueError(f"{key} is inside the output folder and would be erased")
        if not source.is_dir():
            supporting_issues.append(f"{key} does not exist: {source}")
            continue
        for file in source.rglob("*"):
            if file.is_file():
                supporting_hashes[str(file)] = digest(file)
    if manufacturer == "pcbway":
        sections = [
            "01-Schematics",
            "02-PCB-Layout",
            "03-ERC-DRC-Reports",
            "04-Fabrication",
            "05-Assembly",
            "06-Mechanical",
            "07-Ordering-PCBWay",
            "08-Bring-Up-Test-Plan",
            "09-Reference",
        ]
    else:
        sections = [
            "01-Schematics",
            "02-PCB-Layout",
            "03-ERC-DRC-Reports",
            "04-Fabrication",
            "05-Assembly",
        ]
        docs = config.get("docs_dir")
        if docs:
            docs_path = (config_path.parent / docs).resolve()
            if docs_path.is_dir():
                sections = sorted(
                    set(sections)
                    | {
                        path.name
                        for path in docs_path.iterdir()
                        if path.is_dir() and re.match(r"^\d\d-", path.name)
                    }
                )
        mechanical = config.get("mechanical_dir")
        if mechanical and (config_path.parent / mechanical).is_dir():
            sections = sorted(set(sections) | {"06-Mechanical"})
    return {
        "manufacturer": manufacturer,
        "config": str(config_path),
        "output": str(output),
        "board": str(board),
        "inventory": inventory,
        "supporting_files": len(supporting_hashes),
        "supporting_issues": supporting_issues,
        "quote_unknowns": quote_unknowns(manufacturer, config),
        "output_state": output_state(output),
        "expected_sections": sections,
        "input_hash": hashlib.sha256(
            (
                inventory["fingerprint"]
                + digest(config_path)
                + json.dumps(supporting_hashes, sort_keys=True)
            ).encode()
        ).hexdigest(),
    }


def _board_export_config(
    board: Path, manufacturer: str, cli: Path, output: Path, config_dir: Path
) -> dict[str, Any]:
    inventory = project_inventory(board)

    def relative(path):
        return os.path.relpath(path, config_dir)

    if manufacturer == "pcbpower":
        existing = board.parent / "tools" / "export_config_rev_b.json"
        config = load_config(existing) if existing.is_file() else {}
        config.update(
            {
                "project_dir": relative(board.parent),
                "name": board.stem,
                "prefix": config.get("prefix", board.stem),
                "output_dir": relative(output),
                "facts_file": relative(output / "EXPORT-FACTS.json"),
                "kicad_cli": str(cli),
                "render_3d": config.get("render_3d", True),
            }
        )
        if existing.is_file() and config.get("docs_dir"):
            config["docs_dir"] = relative((existing.parent / config["docs_dir"]).resolve())
        else:
            config["docs_dir"] = None
        if config.get("mechanical_dir"):
            config["mechanical_dir"] = relative(
                (existing.parent / config["mechanical_dir"]).resolve()
            )
        config.setdefault(
            "gerber_layers",
            ",".join(
                [
                    *inventory["copper_layers"],
                    "F.Mask",
                    "B.Mask",
                    "F.Paste",
                    "B.Paste",
                    "F.Silkscreen",
                    "B.Silkscreen",
                    "Edge.Cuts",
                ]
            ),
        )
        return config
    if manufacturer == "pcbway":
        order = {key: None for key in QUOTE_FIELDS}
        order.update(
            {
                "layer_count": len(inventory["copper_layers"]),
                "standard_stackup_id": None,
                "stackup_status": None,
                "inner_residual_copper_percent": None,
                "impedance_requirements": [],
                "special_notes": None,
            }
        )
        return {
            "project_dir": relative(board.parent),
            "name": board.stem,
            "prefix": board.stem,
            "output_dir": relative(output),
            "kicad_cli": str(cli),
            "render_3d": True,
            "facts_file": relative(output / "EXPORT-FACTS.json"),
            "gerber_layers": "auto",
            "pcbway": order,
        }
    raise ValueError("Unknown manufacturer")


def configured_profile(board_file: Path, manufacturer: str, all_boards: bool) -> Path | None:
    board = board_file.resolve()
    path = (
        (board.parent.parent / ".traceforge-manufacturing" / manufacturer / "bundle.json")
        if all_boards
        else (board.parent / ".traceforge-manufacturing" / f"{manufacturer}.json")
    )
    return path if path.is_file() else None


def create_starter_config(board_file: Path, manufacturer: str, cli: Path) -> Path:
    inventory = project_inventory(board_file)
    board = Path(inventory["board"])
    if manufacturer not in ("pcbpower", "pcbway"):
        raise ValueError("Unknown manufacturer")
    config_dir = board.parent / ".traceforge-manufacturing"
    config_dir.mkdir(exist_ok=True)
    target = config_dir / f"{manufacturer}.json"
    if target.exists():
        raise FileExistsError(f"Existing configuration will not be overwritten: {target}")
    output = board.parent.parent / "deliverables" / f"TraceForge-{manufacturer}-single" / board.stem
    config = _board_export_config(board, manufacturer, cli, output, config_dir)
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return target


def create_bundle_starter(board_file: Path, manufacturer: str, cli: Path) -> Path:
    board = board_file.resolve()
    root = board.parent.parent
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and (path / f"{path.name}.kicad_pcb").is_file()
        and (path / f"{path.name}.kicad_sch").is_file()
    )
    if not candidates:
        raise ValueError("No sibling KiCad board projects found")
    config_dir = root / ".traceforge-manufacturing" / manufacturer
    manifest = config_dir / "bundle.json"
    if manifest.exists():
        raise FileExistsError(f"Existing bundle will not be overwritten: {manifest}")
    config_dir.mkdir(parents=True, exist_ok=True)
    names = []
    bundle_output = root.parent / "deliverables" / f"TraceForge-{manufacturer}"
    for directory in candidates:
        board_path = directory / f"{directory.name}.kicad_pcb"
        config = _board_export_config(
            board_path, manufacturer, cli, bundle_output / directory.name, config_dir
        )
        name = f"{directory.name}.json"
        path = config_dir / name
        if path.exists():
            raise FileExistsError(f"Existing board config will not be overwritten: {path}")
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        names.append(name)
    manifest.write_text(
        json.dumps(
            {
                "bundle_output_dir": os.path.relpath(bundle_output, config_dir),
                "board_configs": names,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def preview_bundle(manufacturer: str, manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = load_config(manifest_path)
    root = (manifest_path.parent / manifest["bundle_output_dir"]).resolve()
    board_previews = [
        preview_package(manufacturer, (manifest_path.parent / item).resolve())
        for item in manifest["board_configs"]
    ]
    if not board_previews or any(Path(item["output"]).parent != root for item in board_previews):
        raise ValueError("Each board output must be a direct child of bundle output")
    if len({item["output"] for item in board_previews}) != len(board_previews):
        raise ValueError("Bundle contains duplicate output directories")
    fingerprint = hashlib.sha256(
        (
            digest(manifest_path)
            + str(root)
            + "".join(item["input_hash"] for item in board_previews)
        ).encode()
    ).hexdigest()
    return {
        "manufacturer": manufacturer,
        "manifest": str(manifest_path),
        "output": str(root),
        "boards": board_previews,
        "input_hash": fingerprint,
        "output_state": bundle_output_state(root, board_previews),
    }


def bundle_output_state(root: Path, boards: list[dict[str, Any]]) -> dict[str, Any]:
    if not root.exists():
        return {"exists": False, "managed": False, "extra_files": []}
    allowed = {"README.md", "BUNDLE-FACTS.json"}
    for board in boards:
        output = Path(board["output"])
        allowed.add(output.name)
        allowed.add(input_sidecar(output).name)
    extras = sorted(path.name for path in root.iterdir() if path.name not in allowed)
    marker = root / "BUNDLE-FACTS.json"
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
        managed = record.get("manufacturer") in ("pcbpower", "pcbway") and isinstance(
            record.get("boards"), list
        )
    except (OSError, ValueError, AttributeError):
        managed = False
    return {"exists": True, "managed": managed, "extra_files": extras}


def engineering_preview(preview: dict[str, Any], checks: list[dict[str, Any]] | None = None) -> str:
    """Human-readable review of project readiness and planned deliverables."""
    boards = preview.get("boards", [preview])
    lines = [
        f"MANUFACTURER  {preview['manufacturer'].upper()}",
        f"SCOPE         {len(boards)} board{'s' if len(boards) != 1 else ''}",
        f"OUTPUT        {preview['output']}",
        "",
    ]
    for index, board in enumerate(boards, 1):
        inventory = board["inventory"]
        state = board["output_state"]
        name = Path(board["board"]).stem
        config = load_config(Path(board["config"]))
        lines.extend(
            [
                f"{index}. {name}",
                f"   Design: {len(inventory['copper_layers'])} copper layers "
                f"({', '.join(inventory['copper_layers'])}); "
                f"{len(inventory['sheets'])} schematic sheets",
                f"   Libraries: {len(inventory['libraries'])} project-local entries; "
                f"{sum(item['severity'] == 'error' for item in inventory['issues'])} errors; "
                f"{sum(item['severity'] == 'warning' for item in inventory['issues'])} warnings",
                f"   Manufacturer choices: {len(board['quote_unknowns'])} still unselected",
                (
                    f"   Package: "
                    f"{'not generated' if not state['exists'] else 'files intact; release status below' if state['managed'] and not state.get('extra_files') and not state.get('missing_files') and not state.get('changed_files') else 'exists; files need review'}"  # noqa: E501 - composed report text or resource path
                ),
            ]
        )
        if state["exists"] and state["managed"]:
            release = package_release_state(Path(board["output"]), board["quote_unknowns"])
            lines.append(
                
                    f"   Release: "
                    f"{'HOLD - ' + '; '.join(release['reasons'][:3]) if release['hold'] else 'export checks passed; CAM approval pending'}"  # noqa: E501 - composed report text or resource path
                
            )
        if board["manufacturer"] == "pcbpower":
            lines.append(
                f"   CAM notes: {'linked' if config.get('docs_dir') else 'none linked'}; "
                f"assembly exclusions: "
                f"{'reviewed project rules' if config.get('not_assembled_refs') else 'default rules'}"  # noqa: E501 - composed report text or resource path
            )
            mechanical = config.get("mechanical_dir")
            if mechanical:
                source = (Path(board["config"]).parent / mechanical).resolve()
                lines.append(
                    
                        f"   Mechanical files: "
                        f"{sum(path.is_file() for path in source.rglob('*')) if source.is_dir() else 0} linked"  # noqa: E501 - composed report text or resource path
                    
                )
        else:
            order = config["pcbway"]
            lines.append(
                f"   Assembly: {order.get('assembly_mode') or 'not selected'}; "
                f"stackup: {order.get('standard_stackup_id') or 'not selected'}"
            )
        if board["quote_unknowns"]:
            lines.append(
                "   Needed from quote: "
                + ", ".join(field.replace("_", " ") for field in board["quote_unknowns"])
            )
        for issue in inventory["issues"]:
            if issue["severity"] in ("error", "warning"):
                lines.append(f"   {issue['severity'].upper()}: {issue['kind']} — {issue['path']}")
        for issue in board["supporting_issues"]:
            lines.append("   MISSING SUPPORT FILES: " + issue)
        if state.get("extra_files") or state.get("changed_files") or state.get("missing_files"):
            lines.append(
                f"   Output changes: {len(state.get('extra_files', []))} extra, "
                f"{len(state.get('changed_files', []))} edited, "
                f"{len(state.get('missing_files', []))} missing"
            )
            for key, label in (
                ("extra_files", "extra"),
                ("changed_files", "edited"),
                ("missing_files", "missing"),
            ):
                lines.extend(f"     {label}: {name}" for name in state.get(key, []))
        if checks and index <= len(checks):
            result = checks[index - 1]["checks"]
            lines.append(
                "   KiCad checks: "
                + "; ".join(
                    f"{item['check']} {item['findings']} findings"
                    + (" (failed)" if item["return_code"] else "")
                    for item in result["checks"]
                )
            )
            parity = result["bom_centroid"]
            lines.append(
                f"   Assembly: {parity.get('bom_references', '?')} BOM refs; "
                f"{parity.get('centroid_references', '?')} centroid refs; "
                f"{'HOLD' if parity['hold'] else 'parity checked'}"
            )
        lines.append("")
    lines.append("PLANNED PACKAGE")
    for board in boards:
        lines.append("  " + Path(board["board"]).stem)
        lines.extend("    " + section for section in board["expected_sections"])
    lines.extend(
        [
            "  Includes schematic and board views, KiCad source, fabrication archive and drills,",
            "  ERC/DRC reports, BOM and placement data, ordering notes, and checksums.",
            "",
            "NEXT STEP",
            "  Review manufacturer choices, run KiCad checks, then generate a new package.",
            "  Export checks do not establish manufacturer CAM or assembly approval.",
        ]
    )
    return "\n".join(lines)


def find_export_python() -> Path:
    candidates = [Path(sys.executable)]
    for name in ("python", "py"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in dict.fromkeys(candidates):
        result = subprocess.run(
            [str(candidate), "-c", "import openpyxl"], capture_output=True, timeout=8, check=False
        )
        if result.returncode == 0:
            return candidate
    raise RuntimeError("No Python with openpyxl is available for the vendor exporters")


def run_cli_preflight(preview: dict[str, Any], cli: Path) -> dict[str, Any]:
    if not cli.is_file():
        raise FileNotFoundError(cli)
    inventory = preview["inventory"]
    findings = []
    config = load_config(Path(preview["config"]))
    bom_position = {}
    with tempfile.TemporaryDirectory(prefix="traceforge-preflight-") as temporary:
        for label, command in (
            ("ERC", ["sch", "erc", "--severity-all", "-o"]),
            ("DRC", ["pcb", "drc", "--schematic-parity", "--refill-zones", "--severity-all", "-o"]),
        ):
            report = Path(temporary) / f"{label}.rpt"
            source = inventory["schematic"] if label == "ERC" else inventory["board"]
            result = subprocess.run(
                [str(cli), *command, str(report), source],
                cwd=inventory["project"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            content = (
                report.read_text(encoding="utf-8", errors="replace") if report.is_file() else ""
            )
            count = len(re.findall(r"(?m)^\s*\[[^\]]+\]", content))
            findings.append(
                {
                    "check": label,
                    "return_code": result.returncode,
                    "findings": count,
                    "report_exists": report.is_file(),
                    "command_error": (result.stdout + result.stderr)[-1500:]
                    if result.returncode
                    else "",
                }
            )
        bom_position = _bom_position_preflight(inventory, config, cli, Path(temporary))
    return {
        "checks": findings,
        "bom_centroid": bom_position,
        "fabrication_archive": "Checked after export, when the Gerber ZIP exists",
        "hold": bool(
            preview["quote_unknowns"]
            or bom_position["hold"]
            or [item for item in inventory["issues"] if item["severity"] == "error"]
            or any(
                item["return_code"] or item["findings"] or not item["report_exists"]
                for item in findings
            )
        ),
    }


def _footprint_kinds(board: Path) -> dict[str, str]:
    text = board.read_text(encoding="utf-8-sig", errors="replace")
    kinds = {}
    for match in re.finditer(r"\(footprint\s", text):
        form = text[match.start() : _form_end(text, match.start())]
        reference = re.search(r'\(property\s+"Reference"\s+"([^"\r\n]+)"', form)
        if not reference:
            continue
        attr = re.search(r"\(attr\s+([^)]*)\)", form)
        through = bool(
            (attr and "through_hole" in attr.group(1).split())
            or re.search(r'\(pad\s+"[^"\r\n]*"\s+thru_hole\b', form)
        )
        kinds[reference.group(1)] = "THT" if through else "SMD"
    return kinds


def _bom_position_preflight(
    inventory: dict[str, Any], config: dict[str, Any], cli: Path, temporary: Path
) -> dict[str, Any]:
    fields = "Reference,Value,Footprint,Manufacturer,MPN,PCBWay Source Mode"
    bom_file = temporary / "bom.csv"
    position_file = temporary / "position.csv"
    commands = (
        [
            str(cli),
            "sch",
            "export",
            "bom",
            "--fields",
            fields,
            "--labels",
            fields,
            "--exclude-dnp",
            "--ref-range-delimiter",
            "",
            "-o",
            str(bom_file),
            inventory["schematic"],
        ],
        [
            str(cli),
            "pcb",
            "export",
            "pos",
            "--side",
            "both",
            "--format",
            "csv",
            "--units",
            "mm",
            "--smd-only",
            "--exclude-dnp",
            "-o",
            str(position_file),
            inventory["board"],
        ],
    )
    failures = []
    for command in commands:
        result = subprocess.run(
            command,
            cwd=inventory["project"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            failures.append((result.stdout + result.stderr)[-1000:])
    if failures or not bom_file.is_file() or not position_file.is_file():
        return {"hold": True, "errors": failures or ["BOM or centroid export missing"]}
    with bom_file.open(encoding="utf-8-sig", newline="") as stream:
        bom = list(csv.DictReader(stream))
    with position_file.open(encoding="utf-8-sig", newline="") as stream:
        positions = list(csv.DictReader(stream))
    not_ref = re.compile(config.get("not_assembled_refs", r"^(TP.*|FID\d+|MH\d+|LOGO\d*)$"))
    not_footprint = re.compile(
        config.get("not_assembled_footprints", r"FID|MountingHole|MH_"), re.I
    )
    kinds = _footprint_kinds(Path(inventory["board"]))
    bom_refs = set()
    missing_mpn = []
    for row in bom:
        refs = [ref.strip() for ref in (row.get("Reference") or "").split(",")]
        refs = [ref for ref in refs if ref and not ref.startswith("#") and not not_ref.match(ref)]
        bom_refs.update(refs)
        source_mode = (row.get("PCBWay Source Mode") or "").casefold()
        vendor_sourced = preview_vendor_sourced(config, source_mode)
        if refs and vendor_sourced and not (row.get("MPN") or "").strip():
            missing_mpn.extend(refs)
    smd = {ref for ref in bom_refs if kinds.get(ref) == "SMD"}
    unknown_mount = sorted(ref for ref in bom_refs if ref not in kinds)
    position_refs = {
        row.get("Ref", "").strip()
        for row in positions
        if row.get("Ref", "").strip()
        and not not_ref.match(row["Ref"].strip())
        and not not_footprint.search(row.get("Package", ""))
    }
    missing_positions = sorted(smd - position_refs)
    extra_positions = sorted(position_refs - bom_refs)
    return {
        "hold": bool(missing_mpn or unknown_mount or missing_positions or extra_positions),
        "bom_references": len(bom_refs),
        "smd_references": len(smd),
        "centroid_references": len(position_refs),
        "missing_mpn": sorted(set(missing_mpn)),
        "unknown_mount": unknown_mount,
        "smd_missing_from_centroid": missing_positions,
        "centroid_missing_from_bom": extra_positions,
    }


def preview_vendor_sourced(config: dict[str, Any], source_mode: str) -> bool:
    if "pcbway" not in config:
        return True
    if source_mode in ("customer", "consigned"):
        return False
    if not source_mode and config["pcbway"].get("assembly_mode") != "turnkey":
        return False
    return True


def input_sidecar(output: Path) -> Path:
    return output.with_name(output.name + ".traceforge-inputs.json")


def change_state(preview: dict[str, Any]) -> str:
    sidecar = input_sidecar(Path(preview["output"]))
    if not sidecar.is_file():
        return "No TraceForge export snapshot recorded"
    recorded = json.loads(sidecar.read_text(encoding="utf-8"))
    return (
        "Unchanged"
        if recorded.get("input_hash") == preview["input_hash"]
        else "Inputs changed since export"
    )


def package_release_state(output: Path, quote_unknowns: list[str]) -> dict[str, Any]:
    facts_path = output / "EXPORT-FACTS.json"
    if not facts_path.is_file():
        return {"hold": True, "reasons": ["EXPORT-FACTS.json is missing"]}
    try:
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"hold": True, "reasons": ["EXPORT-FACTS.json cannot be read"]}
    reasons = [f"Quote field unknown: {field}" for field in quote_unknowns]
    reasons.extend(facts.get("unresolved_release_items", []))
    checks = facts.get("package_preflight", {})
    reasons.extend(checks.get("errors", []))
    status = checks.get("release_status")
    if status and status.upper().startswith("HOLD"):
        reasons.append(f"Package release status: {status}")
    for name, report in facts.get("reports", {}).items():
        if isinstance(report, dict) and report.get("errors", report.get("errors_detected", 0)):
            reasons.append(f"{name} report has errors")
    return {"hold": bool(reasons), "reasons": sorted(set(reasons))}


def export_package(preview: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    verify_bundled_exporters()
    current = preview_package(preview["manufacturer"], Path(preview["config"]))
    if current["input_hash"] != preview["input_hash"]:
        raise ValueError("Project or config changed since preview")
    if current["supporting_issues"]:
        raise ValueError("Supporting documents missing: " + "; ".join(current["supporting_issues"]))
    state = current["output_state"]
    if state["exists"] and not replace:
        raise FileExistsError("Output exists; preview it and choose Replace generated output")
    if replace and (
        not state["exists"]
        or not state["managed"]
        or state["extra_files"]
        or state["changed_files"]
    ):
        raise ValueError(
            "Output changed, contains unmanaged or edited files, or lacks its manifest"
        )
    python = find_export_python()
    log_dir = Path(os.environ.get("APPDATA", Path.home())) / "TraceForge" / "manufacturing-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"export-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    command = [
        str(python),
        str(WRAPPER),
        "--manufacturer",
        preview["manufacturer"],
        "--config",
        preview["config"],
    ]
    if replace:
        command.append("--replace-output")
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
    after = preview_package(preview["manufacturer"], Path(preview["config"]))
    stale_during_export = after["input_hash"] != preview["input_hash"]
    output = Path(preview["output"])
    release = package_release_state(output, preview["quote_unknowns"])
    integrity = output_state(output)
    integrity_bad = not integrity["managed"] or bool(
        integrity["extra_files"] or integrity["missing_files"] or integrity["changed_files"]
    )
    if output.exists():
        input_sidecar(output).write_text(
            json.dumps(
                {
                    "manufacturer": preview["manufacturer"],
                    "input_hash": preview["input_hash"],
                    "source_hashes": preview["inventory"]["source_hashes"],
                    "config": preview["config"],
                    "export_exit_code": result.returncode,
                    "stale_during_export": stale_during_export,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "output": str(output),
        "log": str(log),
        "exit_code": result.returncode,
        "hold": bool(result.returncode or stale_during_export or release["hold"] or integrity_bad),
        "release_reasons": release["reasons"],
        "output_integrity": integrity,
        "stale_during_export": stale_during_export,
    }


def export_bundle(preview: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    verify_bundled_exporters()
    current = preview_bundle(preview["manufacturer"], Path(preview["manifest"]))
    if current["input_hash"] != preview["input_hash"]:
        raise ValueError("Bundle inputs changed since preview")
    for board in current["boards"]:
        if board["supporting_issues"]:
            raise ValueError(
                "Supporting documents missing: " + "; ".join(board["supporting_issues"])
            )
    state = current["output_state"]
    if state["exists"] and not replace:
        raise FileExistsError("Bundle exists; preview it and choose Replace generated output")
    if replace and (not state["exists"] or not state["managed"] or state["extra_files"]):
        raise ValueError("Bundle contains unmanaged files or lacks its generated-package marker")
    for board in current["boards"]:
        output = board["output_state"]
        if output["exists"] and (
            not output["managed"] or output["extra_files"] or output["changed_files"]
        ):
            raise ValueError(f"Board output has unmanaged or edited files: {board['output']}")
    python = find_export_python()
    log_dir = Path(os.environ.get("APPDATA", Path.home())) / "TraceForge" / "manufacturing-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"bundle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    command = [
        str(python),
        str(WRAPPER),
        "--manufacturer",
        preview["manufacturer"],
        "--manifest",
        preview["manifest"],
    ]
    if replace:
        command.append("--replace-output")
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
    after = preview_bundle(preview["manufacturer"], Path(preview["manifest"]))
    stale = after["input_hash"] != preview["input_hash"]
    release = []
    for board in preview["boards"]:
        output = Path(board["output"])
        release.append(
            {
                "board": board["board"],
                **package_release_state(output, board["quote_unknowns"]),
                "output_integrity": output_state(output),
            }
        )
        if output.exists():
            input_sidecar(output).write_text(
                json.dumps(
                    {
                        "manufacturer": preview["manufacturer"],
                        "input_hash": board["input_hash"],
                        "source_hashes": board["inventory"]["source_hashes"],
                        "config": board["config"],
                        "export_exit_code": result.returncode,
                        "stale_during_export": stale,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    return {
        "output": preview["output"],
        "log": str(log),
        "exit_code": result.returncode,
        "hold": bool(
            result.returncode
            or stale
            or any(
                item["hold"]
                or not item["output_integrity"]["managed"]
                or item["output_integrity"]["extra_files"]
                or item["output_integrity"]["missing_files"]
                or item["output_integrity"]["changed_files"]
                for item in release
            )
        ),
        "board_release_states": release,
        "stale_during_export": stale,
    }
