"""Deterministic BOM quantity/tier arithmetic and timestamped retail cache."""

from __future__ import annotations

import copy
import json
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from . import component_occurrences, component_schema, lcsc_retail
from .cancellation import wait_future

CACHE = Path(os.environ.get("APPDATA", Path.home())) / "TraceForge/lcsc-retail"
LCSC_KEYS = tuple(["LCSC Part #"] + component_schema.SCHEMA["fields"]["LCSC Part #"]["aliases"])


def property_value(properties, keys):
    def normalize(key):
        return re.sub(r"[^a-z0-9]", "", key.casefold())

    folded = {normalize(k): str(v).strip() for k, v in properties.items()}
    return next((folded[normalize(k)] for k in keys if folded.get(normalize(k))), "")


def group_parts(parts):
    grouped = defaultdict(list)
    excluded = []
    for part in parts:
        if part.get("dnp") or part.get("exclude_bom"):
            excluded.append(part["reference"])
            continue
        props = part.get("properties", {})
        normalized = component_schema.properties(props)
        code = normalized.get("LCSC Part #", "")
        match = re.search(r"(?<![A-Za-z0-9])C[0-9]{2,}(?![A-Za-z0-9])", code, re.I)
        code = match.group().upper() if match else ""
        mpn = normalized.get("MPN", "")
        manufacturer = normalized.get("Manufacturer", "")
        # Missing identity stays an individual visible line instead of merging unrelated parts.
        key = (
            code
            if code
            else ("exact", component_occurrences.identity(part))
            if component_occurrences.identity(part)
            else ("missing", part["reference"])
        )
        grouped[key].append(dict(part, lcsc=code, mpn=mpn, manufacturer=manufacturer))
    result = []
    code_mpns = defaultdict(set)
    for group in grouped.values():
        first = group[0]
        for part in group:
            if part["lcsc"] and part["mpn"]:
                code_mpns[part["lcsc"]].add(part["mpn"].casefold())
    for group in grouped.values():
        first = group[0]
        known = next((p for p in group if p["mpn"]), first)
        result.append(
            dict(
                lcsc=first["lcsc"],
                mpn=known["mpn"],
                manufacturer=first["manufacturer"],
                supplier=component_schema.supplier_identity(first.get("properties", {}))[0],
                supplier_code=component_schema.supplier_identity(first.get("properties", {}))[1],
                references=sorted(p["reference"] for p in group),
                per_board=len(group),
                identity_source="; ".join(
                    sorted({p.get("identity_source", "saved supplier field") for p in group})
                ),
                conflict=len(code_mpns[first["lcsc"]]) > 1,
            )
        )
    return result, excluded


def price_line(line, quote, boards=1, spares_percent=0):
    if isinstance(boards, bool) or int(boards) != boards or not 1 <= boards <= 100000:
        raise ValueError("Board quantity must be a positive whole number")
    spares = Decimal(str(spares_percent))
    if not spares.is_finite() or not 0 <= spares <= 100:
        raise ValueError("Spares must be between 0 and 100 percent")
    fitted = line["per_board"] * int(boards)
    demand = int((Decimal(fitted) * (1 + spares / 100)).to_integral_value(rounding=ROUND_CEILING))
    out = dict(
        line,
        fitted_quantity=fitted,
        demand_quantity=demand,
        requested_spares=demand - fitted,
        minimum_order=None,
        order_multiple=None,
        leftover_quantity=None,
        moq_extra_quantity=None,
        order_quantity=demand,
        status="unpriced",
        unit_price_usd=None,
        extended_usd=None,
        observed_at=quote.get("retrieved_at_utc"),
        stock=quote.get("stock"),
    )
    if line.get("conflict"):
        out["status"] = "identity conflict: same LCSC code assigned to different MPNs"
        return out
    if not line["lcsc"]:
        out["status"] = (
            f"{line['supplier']} {line.get('supplier_code', '')}; outside LCSC retail pricing"
            if line.get("supplier") and line.get("supplier_code")
            else "missing LCSC code"
        )
        return out
    if quote.get("lcsc_code") != line["lcsc"]:
        out["status"] = "supplier identity unavailable"
        return out
    if line["mpn"] and quote.get("mpn", "").casefold() != line["mpn"].casefold():
        out["status"] = "supplier MPN mismatch"
        return out
    minimum = quote.get("minimum_order")
    multiple = quote.get("order_multiple")
    out.update(minimum_order=minimum, order_multiple=multiple)
    if quote.get("quantity_schema") == 2 and not (
        isinstance(minimum, int) and minimum > 0 and isinstance(multiple, int) and multiple > 0
    ):
        out["status"] = "supplier minimum order / order multiple unavailable"
        return out
    order = max(demand, minimum if isinstance(minimum, int) and minimum > 0 else demand)
    if isinstance(multiple, int) and multiple > 0:
        order = ((order + multiple - 1) // multiple) * multiple
    out.update(
        order_quantity=order,
        minimum_order=minimum,
        order_multiple=multiple,
        leftover_quantity=order - fitted,
        moq_extra_quantity=order - demand,
    )
    tiers = []
    for tier in quote.get("price_tiers_usd", []):
        try:
            qty = int(tier["min_quantity"])
            price = Decimal(str(tier["unit_price_usd"]))
            if qty > 0 and qty <= order and price.is_finite() and price > 0:
                tiers.append((qty, price))
        except (ValueError, TypeError, KeyError):
            continue
    if not tiers:
        out["status"] = "no USD price tier for order quantity"
        return out
    threshold, price = max(tiers, key=lambda x: x[0])
    out.update(
        status="priced",
        tier_quantity=threshold,
        unit_price_usd=str(price),
        extended_usd=str(price * order),
        fitted_value_usd=str(price * fitted),
        stock_shortage=isinstance(out["stock"], int) and out["stock"] < order,
    )
    return out


def cached_quote(code, refresh=False, cache_dir=None):
    if not re.fullmatch(r"C[0-9]{2,}", code):
        raise ValueError("Invalid LCSC code")
    path = Path(cache_dir or CACHE) / (code + ".json")
    if not refresh and path.exists():
        data = json.loads(path.read_text())
        if data.get("lcsc_code") == code and data.get("quantity_schema") == 2:
            return dict(data, cache_status="cached")
    data = lcsc_retail.lookup_pricing(code, lambda message: None)
    lcsc_retail.check_cancelled()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return dict(data, cache_status="live")


def estimate(
    parts,
    boards=1,
    spares_percent=0,
    refresh=False,
    cancel=None,
    progress=None,
    lookup=cached_quote,
):
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bom-quote") if cancel else None

    def retrieve(code):
        with lcsc_retail.cancel_requests(cancel):
            return lookup(code, refresh=refresh)

    try:
        groups, excluded = group_parts(parts)
        quotes = {}
        lines = []
        for index, group in enumerate(groups):
            if cancel and cancel.is_set():
                raise RuntimeError(
                    "BOM pricing cancelled; incomplete totals were not presented as complete"
                )
            quote = {}
            error = None
            code = group["lcsc"]
            if code and not group["conflict"]:
                if code not in quotes:
                    try:
                        quotes[code] = (
                            wait_future(pool.submit(retrieve, code), cancel)
                            if pool
                            else lookup(code, refresh=refresh)
                        )
                    except (OSError, ValueError, lcsc_retail.LookupError) as exc:
                        quotes[code] = {"error": str(exc)}
                quote = quotes[code]
                error = quote.get("error")
            row = price_line(group, quote, boards, spares_percent)
            if error:
                row["status"] = "price unavailable: " + error
            row["cache_status"] = quote.get("cache_status", "")
            lines.append(row)
            if progress:
                progress(index + 1, len(groups), code)
        priced = [x for x in lines if x["extended_usd"] is not None]
        total = sum((Decimal(x["extended_usd"]) for x in priced), Decimal(0))
        return dict(
            currency="USD",
            boards=boards,
            spares_percent=spares_percent,
            lines=lines,
            priced_lines=len(priced),
            unpriced_lines=len(lines) - len(priced),
            known_parts_subtotal_usd=str(total),
            complete_parts_total_usd=str(total) if len(priced) == len(lines) else None,
            excluded_references=excluded,
            quotes=quotes,
            generated_at=datetime.now(timezone.utc).isoformat(),
            scope=(
                "LCSC retail parts only; excludes fabrication, assembly, shipping, taxes and fees"
            ),
        )
    finally:
        if pool:
            pool.shutdown(wait=False, cancel_futures=True)


def availability_state(row):
    if not row.get("lcsc") and row.get("supplier") and row.get("supplier_code"):
        return "Other supplier"
    if not row.get("lcsc"):
        return "Unassigned"
    if row.get("conflict") or "mismatch" in row.get("status", ""):
        return "Identity conflict"
    stock = row.get("stock")
    if isinstance(stock, int) and stock < row.get("order_quantity", 0):
        return "Stock short"
    if row.get("extended_usd") is None:
        return "Price missing"
    if stock is None:
        return "Stock unknown"
    return "Ready"


def update_assignment(report, references, properties, cancel=None, lookup=cached_quote):
    """Reprice changed SKU groups without re-exporting or resolving the whole BOM."""
    return update_assignments(report, [(references, properties)], cancel=cancel, lookup=lookup)


def update_assignments(report, changes, cancel=None, lookup=cached_quote):
    """Apply a complete batch to snapshots, then group/price once."""
    updates = {}
    for references, properties in changes:
        for ref in references:
            if ref in updates and updates[ref] != properties:
                raise ValueError("Conflicting assignments in the same batch: " + ref)
            updates[ref] = properties
    source = copy.deepcopy(report["source_parts"])
    parts = copy.deepcopy(report.get("resolved_parts", source))
    if "resolved_parts" not in report:
        identities = {ref: row for row in report["lines"] for ref in row["references"]}
        for part in parts:
            row = identities.get(part["reference"])
            if row:
                part.setdefault("properties", {}).update(
                    {"LCSC Part #": row["lcsc"], "MPN": row["mpn"]}
                )
    for collection in (source, parts):
        for part in collection:
            if cancel is not None and cancel.is_set():
                from .cancellation import OperationCancelled

                raise OperationCancelled("BOM refresh cancelled; saved component fields retained")
            if part["reference"] in updates:
                part.setdefault("properties", {}).update(updates[part["reference"]])
                part["identity_source"] = "explicit supplier assignment"
    quotes = dict(report.get("quotes", {}))

    def reuse(code, refresh=False):
        if code not in quotes:
            quotes[code] = lookup(code, refresh=False)
        return quotes[code]

    updated = estimate(
        parts, report["boards"], report["spares_percent"], cancel=cancel, lookup=reuse
    )
    result = dict(report, **updated)
    result.update(source_parts=source, resolved_parts=parts)
    result["identity_resolution"] = {
        p["reference"]: p.get("identity_source", "saved supplier field") for p in parts
    }
    # Keep unchanged row objects and their observations intact.
    old = {tuple(row["references"]): row for row in report["lines"]}
    result["lines"] = [
        old.get(tuple(row["references"]), row) if old.get(tuple(row["references"])) == row else row
        for row in result["lines"]
    ]
    return result
