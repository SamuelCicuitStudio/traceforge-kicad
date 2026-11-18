"""Supplier-neutral identities; saved project records never imply live stock/pricing."""

from __future__ import annotations

import dataclasses
import urllib.parse

from . import component_schema as schema
from .lcsc_research_backend import Part

SOURCES = ["Project supplier information", "LCSC", "DigiKey", "Mouser", "element14"]


def search_url(supplier, mpn):
    term = urllib.parse.quote(mpn, safe="")
    return {
        "LCSC": "https://www.lcsc.com/search?q=",
        "DigiKey": "https://www.digikey.com/en/products?keywords=",
        "Mouser": "https://www.mouser.com/c/?q=",
        "element14": "https://www.element14.com/search?st=",
    }.get(supplier, "") + term


def saved_part(part, supplier="Project supplier information"):
    props = schema.properties(part.get("properties", {}))
    if supplier == "Project supplier information":
        supplier, code = schema.supplier_identity(props)
    else:
        supplier = schema.normalize_supplier(supplier)
        field = schema.SCHEMA["suppliers"].get(supplier, {}).get("part_field", "Supplier Part #")
        code = props.get(field, "") if field != "Supplier Part #" else ""
        if props.get("Supplier") == supplier:
            code = code or props.get("Supplier Part #", "")
    if not supplier or not code:
        raise ValueError(
            "No saved order code for this supplier; choose a source or research the exact MPN"
        )
    if not props.get("MPN") or not props.get("Manufacturer"):
        raise ValueError("Saved manufacturer and MPN are required")
    url_field = schema.SCHEMA["suppliers"].get(supplier, {}).get("url_field", "Supplier URL")
    url = props.get(url_field, "") or (
        props.get("Supplier URL", "") if props.get("Supplier") == supplier else ""
    )
    # Product metadata is retained, but historic stock and prices are not promoted to live quotes.
    return Part(
        code=code,
        mpn=props["MPN"],
        manufacturer=props["Manufacturer"],
        package=props.get("Package", "Unknown"),
        description=props.get("Description", "Unknown"),
        specs=props,
        datasheet_url=props.get("Datasheet", ""),
        product_url=url,
        supplier=supplier,
        supplier_code=code,
        supplier_url=url,
        source="saved project supplier information; not live verified",
        verification_source="saved project information",
    )


def refresh_saved(candidate, expected):
    if not expected:
        raise ValueError("No source references for supplier assignment")
    checked = saved_part(expected[0], candidate.supplier)
    if checked.code != candidate.code or checked.mpn.casefold() != candidate.mpn.casefold():
        raise ValueError("Saved supplier identity changed since analysis")
    return dataclasses.replace(checked, verification_source=candidate.verification_source)
