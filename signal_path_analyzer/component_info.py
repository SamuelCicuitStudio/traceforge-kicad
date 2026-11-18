"""Reference-scoped information changes. Never edit shared lib_symbols or geometry."""

from __future__ import annotations

import json
import os
import re
import uuid
from decimal import Decimal
from pathlib import Path

from . import component_library as library
from . import component_schema as schema

INFO_FIELDS = tuple(
    k for k in schema.SCHEMA["fields"] if k not in {"Reference", "Value", "Footprint"}
)


def selected_properties(part, project=None):
    supplied = dict(
        part.specs,
        MPN=part.mpn,
        Manufacturer=part.manufacturer,
        **{
            "LCSC Part #": part.code,
            "Package": part.package,
            "Datasheet": part.datasheet_url,
            "Description": part.description,
        },
    )
    previous = {}
    if project:
        record = library.existing_part(project, part.manufacturer, part.mpn)
        if record and record.get("status") != "ambiguous":
            previous = schema.properties(record)
    known = {**previous, **schema.properties(supplied)}
    props = {k: known.get(k, "") for k in INFO_FIELDS}
    if not all(props.get(k) for k in ("MPN", "Manufacturer", "LCSC Part #")):
        raise ValueError("Selected part needs a confirmed manufacturer, MPN and LCSC code")
    return props


def passive_quantity(value):
    value = str(value).strip().replace(" ", "").replace("\u00b5", "u").replace("\u03bc", "u")
    value = re.sub(r"(?i)(ohms?|[fhr]|\u03a9)$", "", value)
    value = re.sub(
        r"^(\d+)([RkKMG])(\d+)$", lambda m: m[1] + "." + m[3] + ("" if m[2] == "R" else m[2]), value
    )
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))([pnumkKMG]?)", value)
    if not match:
        return None
    powers = {"": 0, "p": -12, "n": -9, "u": -6, "m": -3, "k": 3, "K": 3, "M": 6, "G": 9}
    return Decimal(match[1]) * (Decimal(10) ** powers[match[2]])


def validate_passive(expected, part):
    for old in expected:
        ref = old["reference"]
        key = next(
            (
                name
                for prefix, name in (("C", "Capacitance"), ("R", "Resistance"), ("L", "Inductance"))
                if re.fullmatch(prefix + r"\d+", ref)
            ),
            None,
        )
        if not key:
            continue
        value = next((v for k, v in part.specs.items() if k.casefold() == key.casefold()), None)
        previous = passive_quantity(old.get("value", ""))
        selected = passive_quantity(value) if value else None
        if previous is not None and selected is not None and previous != selected:
            raise ValueError(
                ref + " nominal value differs from the selected part; choose the same value"
            )
        codes = r"(?<!\d)(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)(?!\d)"
        before = re.search(codes, old.get("footprint", ""))
        after = re.search(codes, part.package)
        if before and after and before[1] != after[1]:
            raise ValueError(ref + " package differs; this action keeps the current footprint")


def references(symbol, project_name):
    found = set()
    for instances in symbol.children("instances"):
        projects = instances.children("project")
        active = [p for p in projects if p.arg() == project_name]
        if not active and len(projects) == 1:
            active = projects
        for project in active:
            for path in project.children("path"):
                found.update(str(n.arg()) for n in path.children("reference"))
    if not found:
        found.update(str(p.arg(2)) for p in symbol.children("property") if p.arg() == "Reference")
    return found


def hierarchy(schematic):
    schematic = Path(schematic).resolve()
    root = schematic.parent
    queue = [schematic]
    seen = set()
    files = []
    while queue:
        path = library.within(root, queue.pop())
        if path in seen:
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8-sig")
        node = library.parse(text)
        if node.head != "kicad_sch":
            raise ValueError("Not a KiCad schematic: " + str(path))
        files.append((path, text, node))
        for sheet in node.children("sheet"):
            for prop in sheet.children("property"):
                if prop.arg() in ("Sheetfile", "Sheet file"):
                    queue.append(path.parent / prop.arg(2))
    return files


def check_closed(schematic):
    root = Path(schematic).resolve().parent
    if list(root.rglob("~*.kicad_sch.lck")):
        raise ValueError(
            "Save and close this project's Schematic Editor before Set. "
            "KiCad 10 cannot update live schematic fields safely; PCB Editor can stay open."
        )


def edit_properties(text, symbol, props):
    replacements = []
    new = []
    for key, value in props.items():
        aliases = {schema.fold(k) for k in [key] + schema.SCHEMA["fields"][key]["aliases"]}
        old = [p for p in symbol.children("property") if schema.fold(p.arg()) in aliases]
        if old:
            first = next((p for p in old if p.arg() == key), old[0])
            raw = text[first.start : first.end]
            for n, v in sorted(
                ((first.value[1], key), (first.value[2], value)),
                key=lambda x: x[0].start,
                reverse=True,
            ):
                a, b = n.start - first.start, n.end - first.start
                raw = raw[:a] + json.dumps(v) + raw[b:]
            replacements += [(p.start, p.end, raw if p is first else "") for p in old]
        else:
            new.append(
                f"\n(property {json.dumps(key)} {json.dumps(value)} (at 0 0 0) "
                "(effects (font (size 1.27 1.27)) (hide yes)))"
            )
    if new:
        replacements.append((symbol.end - 1, symbol.end - 1, "".join(new)))
    return replacements


def plan(schematic, expected, props):
    schematic = Path(schematic).resolve()
    check_closed(schematic)
    root = schematic.parent
    wanted = {p["reference"]: p for p in expected}
    if not wanted:
        raise ValueError("Choose at least one component reference")
    props = {k: str(v) for k, v in props.items() if k in INFO_FIELDS}
    writes = {}
    found = set()
    changes = []

    def add(path, data):
        old = library.read_bytes(path)
        writes[str(path.relative_to(root))] = dict(
            before=library.digest(old), data=data, encoding="utf-8"
        )

    for path, text, node in hierarchy(schematic):
        replacements = []
        for symbol in node.children("symbol"):
            refs = references(symbol, schematic.stem)
            targets = refs & set(wanted)
            if not targets:
                continue
            if refs - targets:
                raise ValueError(
                    "Shared hierarchical symbol also serves "
                    + ", ".join(sorted(refs - targets))
                    + ". Include those references or split its sheet instance "
                    "before assigning a different part."
                )
            old = {p.arg(): p.arg(2) for p in symbol.children("property")}
            old_props = schema.properties(old)
            for ref in targets:
                exp = wanted[ref]
                prior = schema.properties(exp.get("properties", {}))
                for key in ("MPN", "Manufacturer", "LCSC Part #"):
                    if old_props.get(key, "") != prior.get(key, ""):
                        raise ValueError(
                            ref + " information changed since BOM calculation; calculate again"
                        )
                if old.get("Value", "") != exp.get("value", "") or old.get(
                    "Footprint", ""
                ) != exp.get("footprint", ""):
                    raise ValueError(
                        ref + " value/footprint changed since BOM calculation; calculate again"
                    )
                changes.append(
                    dict(
                        reference=ref,
                        before=old_props,
                        after=props,
                        footprint=old.get("Footprint", ""),
                        value=old.get("Value", ""),
                    )
                )
            replacements += edit_properties(text, symbol, props)
            found.update(targets)
        for a, b, value in sorted(replacements, key=lambda x: x[0], reverse=True):
            text = text[:a] + value + text[b:]
        if replacements:
            library.parse(text)
            add(path, text)
    if found != set(wanted):
        raise ValueError("References not located: " + ", ".join(sorted(set(wanted) - found)))
    mapping = root / "libraries/traceforge-reference-info.json"
    record = (
        json.loads(mapping.read_text()) if mapping.is_file() else {"version": 1, "references": {}}
    )
    for change in changes:
        record["references"][change["reference"]] = change
    add(mapping, json.dumps(record, indent=2) + "\n")
    return dict(
        project=str(root),
        operation=uuid.uuid4().hex,
        writes=writes,
        changes=changes,
        schematic=str(schematic),
        summary=["Information only: symbol, footprint, value, wiring and routing retained"],
        part=dict(
            symbol="",
            footprint="",
            provenance={"source": "explicit LCSC assignment", "properties": props},
        ),
    )


def install(plan):
    check_closed(plan["schematic"])
    return library.install(plan)


def rollback(plan, journal):
    """Only restore this transaction's exact bytes; never overwrite a later user edit."""
    root = Path(plan["project"])
    folder = Path(journal).parent
    for rel, entry in plan["writes"].items():
        target = library.within(root, root / rel)
        if library.digest(library.read_bytes(target)) != library.digest(library.entry_bytes(entry)):
            raise ValueError("Later edit preserved during rollback: " + str(target))
    for index, (rel, entry) in reversed(list(enumerate(plan["writes"].items()))):
        path = library.within(root, root / rel)
        if library.digest(library.read_bytes(path)) != library.digest(library.entry_bytes(entry)):
            raise ValueError("Later edit preserved during rollback: " + str(path))
        if entry["before"] is None:
            path.unlink()
        else:
            raw = (folder / f"{index}.backup").read_bytes()
            if library.digest(raw) != entry["before"]:
                raise ValueError("Invalid backup")
            temp = path.with_suffix(path.suffix + ".restore")
            temp.write_bytes(raw)
            os.replace(temp, path)

    record = json.loads(Path(journal).read_text())
    record["state"] = "rolled_back"
    Path(journal).write_text(json.dumps(record, indent=2) + "\n")
