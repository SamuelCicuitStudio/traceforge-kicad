"""Canonical component field names and category presentation, shared with PCB skills."""

from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = json.loads(
    Path(__file__).with_name("component_schema.json").read_text(encoding="utf-8-sig")
)


def fold(key):
    return re.sub(r"[^a-z0-9]", "", str(key).casefold())


def properties(part):
    supplied = {
        fold(k): str(v).strip() for k, v in part.items() if isinstance(v, (str, int, float))
    }
    result = {}
    for key, spec in SCHEMA["fields"].items():
        for alias in [key] + spec["aliases"]:
            value = supplied.get(fold(alias), "")
            if value and value.casefold() not in ("unknown", "n/a"):
                result[key] = value
                break
    supplier = normalize_supplier(result.get("Supplier", ""))
    if not supplier:
        available = [
            name
            for name, fields in SCHEMA.get("suppliers", {}).items()
            if result.get(fields["part_field"])
        ]
        if len(available) == 1:
            supplier = available[0]
    if supplier:
        result["Supplier"] = supplier
        field = SCHEMA.get("suppliers", {}).get(supplier, {}).get("part_field")
        generic = result.get("Supplier Part #", "")
        if field and generic and (supplier != "LCSC" or re.fullmatch(r"C\d{2,}", generic, re.I)):
            result.setdefault(field, generic)
        if field and result.get(field):
            result.setdefault("Supplier Part #", result[field])
    return result


def passive_symbol(category):
    return SCHEMA["categories"].get(category, {}).get("symbol", "")


def visible_fields(category):
    return ["Reference", "Value"] + SCHEMA["categories"].get(category, {}).get("visible", [])


def normalize_supplier(value):
    aliases = {
        "lcsc": "LCSC",
        "digikey": "DigiKey",
        "mouser": "Mouser",
        "element14": "element14",
        "farnell": "element14",
        "newark": "element14",
    }
    return aliases.get(fold(value), str(value).strip())


def supplier_identity(props):
    props = properties(props)
    supplier = normalize_supplier(props.get("Supplier", ""))
    providers = ([supplier] if supplier else []) + list(SCHEMA.get("suppliers", {}))
    for name in dict.fromkeys(providers):
        field = SCHEMA.get("suppliers", {}).get(name, {}).get("part_field")
        code = props.get(field, "") if field else ""
        if name == supplier:
            code = code or props.get("Supplier Part #", "")
        if code:
            return name, code
    return "", ""


def complete_identity(props):
    normalized = properties(props)
    return bool(
        normalized.get("MPN")
        and normalized.get("Manufacturer")
        and supplier_identity(normalized)[1]
    )
