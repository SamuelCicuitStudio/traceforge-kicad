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
    return result


def passive_symbol(category):
    return SCHEMA["categories"].get(category, {}).get("symbol", "")


def visible_fields(category):
    return ["Reference", "Value"] + SCHEMA["categories"].get(category, {}).get("visible", [])
