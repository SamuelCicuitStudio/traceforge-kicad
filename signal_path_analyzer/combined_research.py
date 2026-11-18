"""One component identity, independently observed retail and assembly inventories."""

from __future__ import annotations

import dataclasses
import re
from concurrent.futures import ThreadPoolExecutor

from . import jlc_research_backend as jlc
from . import lcsc_research_backend as lcsc
from .cancellation import wait_future


def folded(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def merge(retail, assembly):
    """C-number and MPN must agree; conflicting packages remain visibly unmerged."""
    if retail.code.upper() != assembly.code.upper():
        return dataclasses.replace(retail, identity_warning="Supplier C-number mismatch")
    for name in ("mpn", "package"):
        a, b = getattr(retail, name), getattr(assembly, name)
        if a in ("", "Unknown") or b in ("", "Unknown"):
            return dataclasses.replace(
                retail, identity_warning="Supplier " + name + " not verified"
            )
        norm_a = re.sub(r"\s+", "", a).casefold() if name == "mpn" else folded(a)
        norm_b = re.sub(r"\s+", "", b).casefold() if name == "mpn" else folded(b)
        if a not in ("", "Unknown") and b not in ("", "Unknown") and norm_a != norm_b:
            # Only standard passive case-code annotations may differ.
            codes = r"(?<!\d)(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)(?!\d)"
            ca, cb = re.search(codes, a), re.search(codes, b)
            if name == "package" and ca and cb and ca[1] == cb[1]:
                continue
            return dataclasses.replace(retail, identity_warning="Supplier " + name + " mismatch")
    return dataclasses.replace(
        retail,
        assembly_tier=assembly.assembly_tier,
        assembly_stock=assembly.stock,
        assembly_prices=assembly.price_tiers,
        assembly_observed_at=assembly.observed_at,
        assembly_source=assembly.source,
        assembly_min_purchase=assembly.min_purchase,
        assembly_min_placement=assembly.min_placement,
    )


def from_assembly(part):
    retail = lcsc.Part(
        code=part.code,
        mpn=part.mpn,
        manufacturer=part.manufacturer,
        package=part.package,
        description=part.description,
        category=part.category,
        specs=part.specs,
        image_url=part.image_url,
        datasheet_url=part.datasheet_url,
        product_url="https://www.lcsc.com/product-detail/" + part.code + ".html",
        source="JLCPCB assembly; retail not checked",
        observed_at=part.observed_at,
    )
    return merge(retail, part)


class CombinedBackend:
    def __init__(self, retail=None, assembly=None):
        self.retail = retail or lcsc.LCSCBackend()
        self.assembly = assembly or jlc.JLCBackend()
        self.retail_categories = []
        self.assembly_categories = []

    def categories(self, cancel=None):
        result = self.retail.categories(cancel)
        self.retail_categories = result[0]
        return result

    def categories_assembly(self, cancel=None):
        result = self.assembly.categories(cancel)
        self.assembly_categories = result[0]
        return result

    def _assembly_query(self, query, cancel=None):
        category_id = None
        if query.category_source == "assembly":
            if not self.assembly_categories:
                self.categories_assembly(cancel)
            return jlc.Query(
                keyword=query.keyword,
                category_id=query.category_id,
                attributes=query.attributes,
                manufacturers=query.manufacturers,
                packages=query.packages,
                in_stock=query.assembly_stock_only,
                tier=query.assembly_tier,
                sort_field=query.sort_field,
                sort_dir=query.sort_dir,
                page=query.page,
                page_size=query.page_size,
            )
        if query.category_id is not None:
            if not self.assembly_categories:
                self.assembly_categories = self.assembly.categories(cancel)[0]

            def walk(nodes):
                return [n for p in nodes for n in [p] + walk(p.children)]

            current = next(
                (c for c in walk(self.retail_categories) if c.id == query.category_id), None
            )
            candidates = [
                c
                for c in walk(self.assembly_categories)
                if current and folded(c.name) == folded(current.name)
            ]
            if not candidates:
                raise lcsc.LCSCError(
                    "No matching JLCPCB category: choose a specific category or search by keyword"
                )
            category_id = candidates[0].id
        return jlc.Query(
            keyword=query.keyword,
            category_id=category_id,
            attributes=query.attributes,
            manufacturers=query.manufacturers,
            packages=query.packages,
            in_stock=query.assembly_stock_only,
            tier=query.assembly_tier,
            sort_field=query.sort_field,
            sort_dir=query.sort_dir,
            page=query.page,
            page_size=query.page_size,
        )

    @staticmethod
    def assembly_mode(query):
        return query.assembly_tier != "all" or query.assembly_stock_only

    def search(self, query, cancel=None):
        if not self.assembly_mode(query):
            return self.retail.search(query, cancel)
        page = self.assembly.search(self._assembly_query(query, cancel), cancel)
        parts = [from_assembly(p) for p in page.parts]
        return lcsc.Page(
            parts,
            page.total,
            page.current_page,
            page.total_pages,
            page.source,
            page.observed_at,
            "JLCPCB assembly catalogue; retail checked separately",
        )

    def filter_groups(self, query, cancel=None):
        if not self.assembly_mode(query):
            return self.retail.filter_groups(query, cancel)
        return self.assembly.filter_groups(self._assembly_query(query, cancel), cancel)

    def enrich(self, parts, cancel=None):
        def one(part):
            if cancel and cancel.is_set():
                raise lcsc.Cancelled("Cancelled")
            try:
                if part.assembly_source != "not checked":
                    retail = self.retail.exact(part.code, cancel)
                    assembly = jlc.Part(
                        code=part.code,
                        mpn=part.mpn,
                        package=part.package,
                        stock=part.assembly_stock,
                        assembly_tier=part.assembly_tier,
                        price_tiers=part.assembly_prices,
                        observed_at=part.assembly_observed_at,
                        source=part.assembly_source,
                        min_purchase=part.assembly_min_purchase,
                        min_placement=part.assembly_min_placement,
                    )
                    return merge(retail, assembly)
                return merge(part, self.assembly.exact(part.code, cancel))
            except (lcsc.LCSCError, jlc.JLCError) as exc:
                if cancel and cancel.is_set():
                    raise lcsc.Cancelled("Cancelled") from exc
                if part.assembly_source != "not checked":
                    return dataclasses.replace(part, source="LCSC unavailable: " + str(exc))
                return dataclasses.replace(part, assembly_source=str(exc))

        pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="supplier-match")
        try:
            futures = [pool.submit(one, part) for part in parts]
            return [wait_future(future, cancel) for future in futures]
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def exact(self, code, cancel=None):
        return self.retail.exact(code, cancel)

    def details(self, part, cancel=None):
        retail = self.retail.details(part, cancel)
        return dataclasses.replace(
            retail,
            **{
                f.name: getattr(part, f.name)
                for f in dataclasses.fields(part)
                if f.name.startswith("assembly_")
            },
        )

    def check_cad(self, *args, **kwargs):
        return self.retail.check_cad(*args, **kwargs)

    def verify_step(self, *args, **kwargs):
        return self.retail.verify_step(*args, **kwargs)

    def image(self, *args, **kwargs):
        return self.retail.image(*args, **kwargs)
