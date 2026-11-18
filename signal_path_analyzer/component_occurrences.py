"""Exact physical-part occurrence matching independent of distributor assignment."""

from . import component_schema as schema


def identity(part):
    props = schema.properties(part.get("properties", {}))
    mpn = props.get("MPN", "").strip().casefold()
    if not mpn or mpn in ("unknown", "n/a", "dnp", "dnf"):
        return None
    return (
        mpn,
        schema.fold(props.get("Manufacturer", "")),
        part.get("footprint", ""),
        str(part.get("value", "")).strip().casefold(),
    )


def expand(parts, references):
    refs = set(references)
    seeds = {identity(p) for p in parts if p["reference"] in refs} - {None}
    return [p for p in parts if p["reference"] in refs or (identity(p) in seeds)]
