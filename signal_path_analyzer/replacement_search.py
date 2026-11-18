"""Replacement criteria derived from actual instance values and supplier filter options."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from . import component_schema as schema
from .component_info import passive_quantity


def number(value):
    text = str(value).strip().replace(" ", "").replace("\u00b5", "u").replace("\u03bc", "u")
    text = re.sub(r"(?i)(ohms?|[fhrvwa]|\u03a9)$", "", text)
    return passive_quantity(text)


def tolerance(value):
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    try:
        return Decimal(match[0]) if match else None
    except InvalidOperation:
        return None


def find_category(categories, kind, hint=""):
    names = {
        "capacitor": "Capacitors",
        "resistor": "Resistors",
        "inductor": "Inductors",
        "bead": "Ferrite Beads",
        "led": "LEDs",
    }
    target = names.get(kind, "")
    if not target:

        def flatten(nodes):
            return [node for parent in nodes for node in [parent] + flatten(parent.children)]

        nodes = flatten(categories)
        folded = schema.fold(hint)
        exact = [node for node in nodes if schema.fold(node.name) == folded and folded]
        if exact:
            return exact[0]
        for token, label in (
            ("tvs", "tvs"),
            ("esd", "esd"),
            ("schottky", "schottky"),
            ("zener", "zener"),
        ):
            if token in hint.casefold():
                matched = [node for node in nodes if label in node.name.casefold()]
                if matched:
                    return min(matched, key=lambda node: len(node.name))
        return None

    def walk(nodes):
        for node in nodes:
            if node.name.casefold() == target.casefold():
                return node
            result = walk(node.children)
            if result:
                return result
        return None

    passives = next((c for c in categories if c.name.casefold() == "passives"), None)
    found = walk(passives.children if passives else categories)
    return found or (find_category(categories, "custom", hint) if hint else None)


def current_settings(parts, supplier=None):
    first = parts[0] if parts else {}
    props = {}
    if supplier:
        props = schema.properties(dict(supplier.specs, Package=supplier.package))
    props.update(schema.properties(first.get("properties", {})))
    ref = first.get("reference", "")
    kind = next(
        (
            kind
            for prefix, kind in (
                ("FB", "bead"),
                ("C", "capacitor"),
                ("R", "resistor"),
                ("L", "inductor"),
                ("D", "led"),
            )
            if re.fullmatch(prefix + r"\d+", ref)
        ),
        "custom",
    )
    package = re.search(
        r"(?<!\d)(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)(?!\d)",
        first.get("footprint", ""),
    )
    if package:
        props["Package"] = package[1]
    hint = supplier.category if supplier else props.get("Description", "")
    if kind == "led" and not re.search(r"(?i)\bled\b|light.emitting", hint):
        kind = "custom"
    return dict(kind=kind, value=first.get("value", ""), properties=props, category_hint=hint)


def choose_filters(groups, settings):
    props = settings["properties"]
    kind = settings["kind"]
    pending = {}
    applied = []
    unmatched = []
    value_group = {
        "capacitor": "Capacitance",
        "resistor": "Resistance",
        "inductor": "Inductance",
        "bead": "Impedance @ Frequency",
    }.get(kind)
    targets = {value_group: (settings["value"], "equal")} if value_group else {}
    for key, title, mode in (
        ("Voltage", "Voltage Rating", "minimum"),
        ("Tolerance", "Tolerance", "maximum"),
        ("Dielectric", "Temperature Coefficient", "equal"),
        ("Power", "Power(Watts)", "minimum"),
        ("Current", "Current Rating", "minimum"),
        ("Saturation Current", "Current - Saturation (Isat)", "minimum"),
    ):
        if props.get(key):
            targets[title] = (props[key], mode)
    if props.get("Package"):
        targets["__package__"] = (props["Package"], "text")
    aliases = {
        "voltage rating (dc)": "voltage rating",
        "voltage - rated": "voltage rating",
        "power rating": "power(watts)",
        "current rating (amps)": "current rating",
    }
    for title, (wanted, mode) in targets.items():
        if not wanted:
            continue
        group = next(
            (
                g
                for g in groups
                if g.key == title
                or aliases.get(g.title.casefold(), g.title.casefold()) == title.casefold()
            ),
            None,
        )
        selected = []
        if group:
            for option in group.options:
                equal = (
                    str(option.label).replace(" ", "").casefold()
                    == str(wanted).replace(" ", "").casefold()
                )
                a = tolerance(option.label) if title == "Tolerance" else number(option.label)
                b = tolerance(wanted) if title == "Tolerance" else number(wanted)
                if title == "Temperature Coefficient":
                    equal = equal or bool(
                        re.search(r"\b" + re.escape(str(wanted)) + r"\b", option.label, re.I)
                    )
                if equal or (
                    a is not None
                    and b is not None
                    and (
                        (mode == "equal" and a == b)
                        or (mode == "minimum" and a >= b)
                        or (mode == "maximum" and a <= b)
                    )
                ):
                    selected.append(option.value)
        if selected:
            pending[group.key] = selected
            qualifier = (
                "at least " if mode == "minimum" else "at most " if mode == "maximum" else ""
            )
            applied.append(title.replace("__package__", "Package") + ": " + qualifier + str(wanted))
        else:
            unmatched.append(title.replace("__package__", "Package") + ": " + str(wanted))
    return pending, applied, unmatched
