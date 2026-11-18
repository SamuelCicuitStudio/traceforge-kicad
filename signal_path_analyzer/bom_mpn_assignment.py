"""Assign confirmed supplier identity for existing exact MPNs, for every part type."""

from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import component_schema as schema
from . import lcsc_research_backend as api
from . import supplier_records
from .cancellation import wait_future


def manufacturer_matches(saved, actual):
    if not saved or saved.casefold() in ("unknown", "n/a"):
        return True
    aliases = {
        "texasinstruments": "ti",
        "stmicroelectronics": "stmicro",
        "st": "stmicro",
        "onsemiconductor": "onsemi",
    }
    a, b = schema.fold(saved), schema.fold(actual)
    a, b = aliases.get(a, a), aliases.get(b, b)
    return bool(
        a and b and (a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a))))
    )


def validate(parts, candidate):
    if not candidate.mpn or candidate.mpn == "Unknown" or not candidate.code:
        raise ValueError("Exact supplier identity unavailable")
    for part in parts:
        props = schema.properties(part.get("properties", {}))
        if props.get("MPN", "").casefold() != candidate.mpn.casefold():
            raise ValueError(part["reference"] + ": MPN differs from the saved component")
        if not manufacturer_matches(props.get("Manufacturer", ""), candidate.manufacturer):
            raise ValueError(part["reference"] + ": manufacturer differs for this MPN")
        # Geometry stays fixed. Block a known standard passive case-size mismatch.
        pattern = r"(?<!\d)(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)(?!\d)"
        a, b = re.search(pattern, part.get("footprint", "")), re.search(pattern, candidate.package)
        if a and b and a[1] != b[1]:
            raise ValueError(
                part["reference"] + ": supplier package differs from the existing footprint"
            )


def scan(report, backend, cancel, progress=None, source="LCSC"):
    groups = defaultdict(list)
    excluded = []
    for part in report.get("source_parts", []):
        if part.get("dnp") or part.get("exclude_bom"):
            continue
        props = schema.properties(part.get("properties", {}))
        mpn = props.get("MPN", "")
        if not mpn or mpn.casefold() in ("unknown", "n/a", "dnp", "dnf"):
            excluded.append(part["reference"])
            continue
        # Never infer a manufacturer number from a generic nominal value.
        key = (
            schema.supplier_identity(props),
            mpn.casefold(),
            props.get("Manufacturer", "").casefold(),
            part.get("footprint", ""),
            part.get("value", ""),
        )
        groups[key].append(part)
    lookup_cache = {}
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mpn-assign")

    def lookup(mpn, maker):
        page = backend.retail.search(api.Query(keyword=mpn, page_size=100), cancel)
        exact = {
            p.code: p
            for p in page.parts
            if p.mpn.casefold() == mpn.casefold() and manufacturer_matches(maker, p.manufacturer)
        }
        if not exact:
            raise ValueError("No exact MPN/manufacturer match; component unchanged")
        if len(exact) != 1 or page.total is None or page.total > len(page.parts):
            raise ValueError(
                "Ambiguous or incomplete supplier search; select an exact C-number manually"
            )
        selected = next(iter(exact.values()))
        detailed = backend.retail.details(selected, cancel)
        if detailed.code != selected.code or detailed.mpn.casefold() != mpn.casefold():
            raise ValueError("Supplier identity changed during lookup")
        return detailed

    try:
        for parts in groups.values():
            if source != "LCSC":
                continue
            props = schema.properties(parts[0].get("properties", {}))
            key = (props["MPN"], props.get("Manufacturer", ""))
            if key not in lookup_cache:
                lookup_cache[key] = pool.submit(lookup, *key)
        proposals = []
        for index, parts in enumerate(groups.values(), 1):
            if cancel.is_set():
                raise api.Cancelled("Exact-MPN assignment cancelled")
            props = schema.properties(parts[0].get("properties", {}))
            refs = sorted(p["reference"] for p in parts)
            row = dict(
                references=refs,
                per_board=len(refs),
                mpn=props["MPN"],
                manufacturer=props.get("Manufacturer", ""),
                lcsc=props.get("LCSC Part #", ""),
            )
            proposal = dict(
                row=row,
                parts=parts,
                candidate=None,
                current=None,
                before=None,
                after=None,
                order=None,
                reason="",
                settings={},
            )
            try:
                selected = (
                    wait_future(lookup_cache[(props["MPN"], props.get("Manufacturer", ""))], cancel)
                    if source == "LCSC"
                    else supplier_records.saved_part(parts[0], source)
                )
                validate(parts, selected)
                if all(
                    p.get("properties", {}).get("MPN", "").casefold() == selected.mpn.casefold()
                    and p.get("properties", {}).get("Manufacturer")
                    and p.get("properties", {}).get("Supplier") == selected.supplier
                    and p.get("properties", {}).get("Supplier Part #") == selected.code
                    for p in parts
                ):
                    proposal["reason"] = "Exact MPN already assigned"
                else:
                    proposal.update(
                        candidate=selected,
                        reason=(
                            "Exact MPN/manufacturer verified; "
                            if source == "LCSC"
                            else "Saved supplier fields; not live verified. "
                        )
                        + "Existing value and footprint retained",
                    )
            except Exception as exc:
                if cancel.is_set():
                    raise api.Cancelled("Exact-MPN assignment cancelled") from exc
                proposal["reason"] = str(exc)
            proposals.append(proposal)
            if progress:
                progress(index, len(groups), ", ".join(refs))
        return dict(proposals=proposals, observations={}, missing_mpn=excluded)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
