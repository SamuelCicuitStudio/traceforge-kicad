"""Conservative, reviewable JLCPCB Basic substitutions for ordinary R/C passives."""

from __future__ import annotations

import dataclasses
import math
import re
from decimal import Decimal

from . import component_schema as schema
from . import jlc_research_backend as jlc
from . import replacement_search as criteria
from .combined_research import from_assembly


@dataclasses.dataclass(frozen=True)
class Parameters:
    scope: str = "Both"
    max_tolerance: str = "Same or tighter"
    require_stock: bool = True
    keep_dielectric: bool = True
    library_tier: str = "basic"


def rating(value):
    parsed = criteria.number(value)
    if parsed is not None:
        return parsed
    fraction = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*[WV]?\s*", str(value), re.I)
    if fraction and int(fraction[2]):
        return Decimal(fraction[1]) / Decimal(fraction[2])
    return None


def search_value(settings):
    value = criteria.number(settings["value"])
    if value is None:
        return settings["value"]
    scales = ((Decimal("1e-6"), "uF"), (Decimal("1e-9"), "nF"), (Decimal("1e-12"), "pF"))
    if settings["kind"] == "resistor":
        scales = ((Decimal("1e6"), "M"), (Decimal("1e3"), "k"), (Decimal(1), "ohm"))
    for scale, suffix in scales:
        if value >= scale:
            return format((value / scale).normalize(), "f") + suffix
    return settings["value"]


def compatible(settings, candidate, params):
    kind = settings["kind"]
    props = settings["properties"]
    new = schema.properties(dict(candidate.specs, Package=candidate.package))
    issues = []
    value_key = "Capacitance" if kind == "capacitor" else "Resistance"
    nominal = next(
        (v for k, v in candidate.specs.items() if k.casefold() == value_key.casefold()), None
    )
    a, b = criteria.number(settings["value"]), criteria.number(nominal or "")
    if a is None or b is None or a != b:
        issues.append("Exact nominal value not verified")
    package = props.get("Package", "")
    if not package or package.casefold() != candidate.package.casefold().strip():
        issues.append("Same package not verified")
    limit = (
        props.get("Tolerance")
        if params.max_tolerance == "Same or tighter"
        else params.max_tolerance
    )
    old_tol, new_tol = criteria.tolerance(limit or ""), criteria.tolerance(new.get("Tolerance", ""))
    if old_tol is None or new_tol is None or new_tol > old_tol:
        issues.append("Tolerance limit not verified")
    rating_keys = ("Voltage",) if kind == "capacitor" else ("Power",)
    if kind == "resistor" and props.get("Voltage"):
        rating_keys += ("Voltage",)
    for key in rating_keys:
        before, after = rating(props.get(key, "")), rating(new.get(key, ""))
        if before is None or after is None or after < before:
            issues.append(key + " rating not verified")
    if kind == "capacitor" and params.keep_dielectric:
        a, b = props.get("Dielectric", ""), new.get("Dielectric", "")
        if not a or not b or a.casefold() != b.casefold():
            issues.append("Same dielectric not verified")
    if kind == "resistor" and props.get("Dielectric"):
        before = criteria.tolerance(props["Dielectric"])
        after = criteria.tolerance(new.get("Dielectric", ""))
        if before is None or after is None or after > before:
            issues.append("Resistor temperature coefficient not verified")
    if props.get("Temperature Coefficient"):
        if new.get("Temperature Coefficient") != props["Temperature Coefficient"]:
            issues.append("Temperature coefficient not verified")
    return issues


def assembly_cost(part, demand):
    if not part or not part.assembly_prices or part.assembly_min_purchase is None:
        return None, None
    order = max(demand, part.assembly_min_purchase, part.assembly_min_placement or 0)
    tiers = [
        (t["quantity"], Decimal(str(t["unit_price"])))
        for t in part.assembly_prices
        if t.get("currency") == "USD" and t["quantity"] <= order
    ]
    return (max(tiers)[1] * order, order) if tiers else (None, order)


def scan(report, backend, params, cancel, progress=None, optimize=True):
    by_ref = {p["reference"]: p for p in report.get("source_parts", [])}
    proposals, observations = [], {}
    candidates_cache = {}
    for index, row in enumerate(report["lines"]):
        if cancel.is_set():
            raise jlc.Cancelled("Cancelled")
        if progress:
            progress(index + 1, len(report["lines"]), ", ".join(row["references"]))
        parts = [by_ref[r] for r in row["references"] if r in by_ref]
        if optimize:
            preliminary = criteria.current_settings(parts)
            if preliminary["kind"] not in ("resistor", "capacitor") or params.scope not in (
                "Both",
                preliminary["kind"].title(),
            ):
                continue
        current = None
        if row["lcsc"]:
            try:
                current = from_assembly(backend.assembly.exact(row["lcsc"], cancel))
                observations[row["lcsc"]] = current
            except jlc.JLCError:
                pass
        if not optimize:
            continue
        if not parts:
            continue
        settings = criteria.current_settings(parts)
        kind = settings["kind"]
        if kind not in ("resistor", "capacitor") or params.scope not in ("Both", kind.title()):
            continue
        proposal = dict(
            row=row,
            candidate=None,
            reason="",
            current=current,
            before=None,
            after=None,
            order=None,
            settings=settings,
        )
        proposals.append(proposal)
        needs_assignment = any(
            not all(
                schema.properties(p.get("properties", {})).get(key)
                for key in ("LCSC Part #", "MPN", "Manufacturer")
            )
            for p in parts
        )
        if (
            current
            and not needs_assignment
            and (current.assembly_tier == "Basic" or params.library_tier == "all")
        ):
            demand = math.ceil(
                row["per_board"] * report["boards"] * (1 + report["spares_percent"] / 100)
            )
            _, order = assembly_cost(current, demand)
            if not params.require_stock or (
                order is not None
                and current.assembly_stock is not None
                and current.assembly_stock >= order
            ):
                proposal["reason"] = (
                    "Already assigned and in stock"
                    if params.library_tier == "all"
                    else "Already Basic; stock requirement satisfied"
                )
                continue
        try:
            supplier = backend.retail.exact(row["lcsc"], cancel) if row["lcsc"] else None
            settings = criteria.current_settings(parts, supplier)
            proposal["settings"] = settings
            package = settings["properties"].get("Package", "")
            if not package or criteria.number(settings["value"]) is None:
                proposal["reason"] = "Value / standard package missing; review required"
                continue
            key = (search_value(settings), package)
            if key not in candidates_cache:
                candidates_cache[key] = []
                query = jlc.Query(
                    keyword=key[0],
                    packages=(package,),
                    tier=params.library_tier,
                    in_stock=params.require_stock,
                    page_size=100,
                )
                page = backend.assembly.search(query, cancel)
                candidates = list(page.parts)
                if params.library_tier == "all":
                    basic_page = backend.assembly.search(
                        dataclasses.replace(query, tier="basic"), cancel
                    )
                    candidates = list({p.code: p for p in candidates + basic_page.parts}.values())
                enriched = backend.enrich([from_assembly(p) for p in candidates], cancel)
                candidates_cache[key] = [
                    p
                    for p in enriched
                    if not p.identity_warning and not p.source.startswith("LCSC unavailable:")
                ]
                if page.total_pages and page.total_pages > 1:
                    proposal["reason"] = "First 100 Basic matches checked; refine in Research"
            demand = math.ceil(
                row["per_board"] * report["boards"] * (1 + report["spares_percent"] / 100)
            )
            matches = []
            reasons = []
            for candidate in candidates_cache[key]:
                issues = compatible(settings, candidate, params)
                for instance in parts[1:]:
                    issues += compatible(
                        criteria.current_settings([instance], supplier), candidate, params
                    )
                if issues:
                    reasons.extend(issues)
                    continue
                cost, order = assembly_cost(candidate, demand)
                if order is None:
                    reasons.append("Assembly minimum quantity unavailable")
                    continue
                if params.require_stock and (
                    candidate.assembly_stock is None or candidate.assembly_stock < order
                ):
                    reasons.append("Insufficient assembly stock")
                    continue
                if cost is None:
                    reasons.append("Assembly price unavailable")
                    continue
                matches.append((cost, candidate.code, order, candidate))
            if matches:
                cost, _, order, candidate = min(
                    matches,
                    key=lambda item: (
                        0 if item[3].assembly_tier == "Basic" else 1,
                        item[0],
                        item[1],
                    ),
                )
                before, _ = assembly_cost(current, demand)
                proposal.update(
                    candidate=candidate,
                    before=before,
                    after=cost,
                    order=order,
                    reason="Verified value, package and configured ratings; review before applying",
                )
            else:
                proposal["reason"] = (
                    "; ".join(dict.fromkeys(reasons)) or "No qualifying in-stock equivalent"
                )
        except Exception as exc:
            if cancel.is_set():
                raise
            proposal["reason"] = str(exc)
    return dict(proposals=proposals, observations=observations)
