"""LCSC-only research backend. No Qt dependency, KiCad integration, or embedded browser.

Public-facing undocumented LCSC website endpoints are used for catalog filters.
They may change or reject anonymous requests. The official signed partner API is
intentionally not impersonated. Models preserve Unknown rather than guessing.
"""

from __future__ import annotations

import dataclasses
import heapq
import html
import itertools
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE = "https://wmsc.lcsc.com"
EASYEDA_API = "https://easyeda.com/api/products/{}/components?version=6.4.19.5"
STEP_API = "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{}"
C_RE = re.compile(r"^C\d{2,}$", re.I)
NEXT_DATA_RE = re.compile(
    r'<script[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S | re.I
)
MAX_BODY = 12 * 1024 * 1024


class LCSCError(Exception):
    pass


class Cancelled(LCSCError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def val(value: Any, default: str = "Unknown") -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def integer(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def price_number(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None


@dataclasses.dataclass(frozen=True)
class Category:
    id: int
    name: str
    children: tuple[Category, ...] = ()


@dataclasses.dataclass(frozen=True)
class Option:
    label: str
    value: str
    range_flag: bool = False
    range_start: Optional[str] = None
    range_end: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class FilterGroup:
    key: str
    title: str
    options: tuple[Option, ...]
    units: tuple[str, ...] = ()
    conversion: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class Query:
    keyword: str = ""
    category_id: Optional[int] = None
    attributes: dict[str, tuple[str, ...]] = dataclasses.field(default_factory=dict)
    manufacturers: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    packaging: tuple[str, ...] = ()
    in_stock: bool = False
    sort_field: str = ""
    sort_dir: str = "asc"
    page: int = 1
    page_size: int = 25
    category_ids: tuple[int, ...] = ()
    assembly_tier: str = "all"
    assembly_stock_only: bool = False
    category_source: str = "retail"


@dataclasses.dataclass
class Part:
    code: str
    mpn: str = "Unknown"
    manufacturer: str = "Unknown"
    package: str = "Unknown"
    description: str = "Unknown"
    category: str = "Unknown"
    product_id: Optional[int] = None
    stock: Optional[int] = None
    image_url: str = ""
    datasheet_url: str = ""
    product_url: str = ""
    price_tiers: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    specs: dict[str, str] = dataclasses.field(default_factory=dict)
    observed_at: str = ""
    source: str = "unverified"
    cad_symbol: str = "unchecked"
    cad_footprint: str = "unchecked"
    cad_step: str = "unchecked"
    cad_step_uuid: str = ""
    assembly_tier: str = "Unknown"
    assembly_stock: Optional[int] = None
    assembly_prices: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    assembly_observed_at: str = ""
    assembly_source: str = "not checked"
    assembly_min_purchase: Optional[int] = None
    assembly_min_placement: Optional[int] = None
    identity_warning: str = ""
    supplier: str = "LCSC"
    supplier_code: str = ""
    supplier_url: str = ""
    verification_source: str = ""

    def cad_record(self) -> dict[str, Any]:
        """Minimal, stable, read-only handoff for existing CAD downloaders."""
        return {
            "source": "LCSC",
            "lcsc_id": self.code,
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "package": self.package,
            "easyeda_lookup_url": EASYEDA_API.format(self.code),
            "cad": {
                "symbol": self.cad_symbol,
                "footprint": self.cad_footprint,
                "step": self.cad_step,
                "step_uuid": self.cad_step_uuid,
            },
            "observation": {"data_source": self.source, "observed_at": self.observed_at},
        }


@dataclasses.dataclass
class Page:
    parts: list[Part]
    total: Optional[int]
    current_page: int
    total_pages: Optional[int]
    source: str
    observed_at: str
    note: str = ""


@dataclasses.dataclass
class Response:
    data: Any
    source: str
    observed_at: str


class Cache:
    """Small disk cache for public catalog metadata / short-lived inventory."""

    def __init__(self, root: Optional[Path] = None):
        self.root = (
            root or Path(os.environ.get("APPDATA", Path.home())) / "TraceForge" / "lcsc-research-v1"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _path(self, key: str) -> Path:
        import hashlib

        return self.root / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key: str, max_age: int) -> Optional[Response]:
        path = self._path(key)
        try:
            with self.lock:
                obj = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(obj["epoch"]) <= max_age:
                return Response(obj["data"], "cached", obj["observed_at"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def put(self, key: str, value: Any) -> None:
        path = self._path(key)
        obj = {"epoch": time.time(), "observed_at": utc_now(), "data": value}
        temp = path.with_suffix(".tmp")
        with self.lock:
            temp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)


class Transport:
    """Bounded HTTP transport. Mock transports can implement request(...)."""

    def __init__(self, timeout: float = 8.0):
        self.timeout = max(1.0, min(float(timeout), 20.0))

    def request(
        self,
        method: str,
        url: str,
        payload: Optional[dict] = None,
        cancel: Optional[threading.Event] = None,
        max_bytes: int = MAX_BODY,
        partial: bool = False,
    ) -> Any:
        if cancel is not None and cancel.is_set():
            raise Cancelled("Request cancelled")
        host = urllib.parse.urlparse(url).hostname
        if host not in {
            "wmsc.lcsc.com",
            "www.lcsc.com",
            "easyeda.com",
            "modules.easyeda.com",
            "assets.lcsc.com",
        }:
            raise LCSCError("Blocked unexpected host")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html;q=0.9, image/*;q=0.8, */*;q=0.5",
            "Accept-Encoding": "identity",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        if host == "wmsc.lcsc.com":
            headers["Referer"] = "https://www.lcsc.com/"
            headers["Origin"] = "https://www.lcsc.com"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                chunks = bytearray()
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled("Request cancelled")
                    remain = max_bytes - len(chunks) if partial else max_bytes + 1 - len(chunks)
                    if partial and remain <= 0:
                        break
                    chunk = resp.read(min(65536, remain))
                    if not chunk:
                        break
                    chunks += chunk
                    if len(chunks) > max_bytes:
                        raise LCSCError("Provider response exceeds safety limit")
                    if partial and len(chunks) >= max_bytes:
                        break
        except urllib.error.HTTPError as e:
            raise LCSCError(f"{host}: HTTP {e.code}; provider may block automated requests") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LCSCError(f"{host}: connection error / timeout: {e}") from e
        if cancel is not None and cancel.is_set():
            raise Cancelled("Request cancelled")
        if host == "assets.lcsc.com" or host == "modules.easyeda.com":
            return bytes(chunks)
        if host == "www.lcsc.com" and "/product-detail/" in url:
            return chunks.decode("utf-8-sig", errors="replace")
        try:
            return json.loads(chunks.decode("utf-8-sig"))
        except (UnicodeError, ValueError) as e:
            raise LCSCError(f"{host} returned HTML or malformed JSON instead of API data") from e


SORTS = {"", "price", "stock", "brand", "model", "encapStandard", "productArrange"}


def query_payload(query: Query, for_filters: bool = False) -> dict[str, Any]:
    """All selected filters sent to LCSC, never applied to one local result page."""
    if query.page < 1 or not (1 <= query.page_size <= 100):
        raise LCSCError("Page must be >=1 and page size 1–100")
    if query.sort_field not in SORTS or query.sort_dir not in ("asc", "desc"):
        raise LCSCError("Unsupported sorting option")
    payload: dict[str, Any] = {
        "keyword": query.keyword.strip(),
        "catalogIdList": [query.category_id] if query.category_id is not None else [],
        "brandIdList": list(query.manufacturers),
        "encapValueList": list(query.packages),
        "productArrangeList": list(query.packaging),
        "paramNameValueMap": {k: list(v) for k, v in query.attributes.items() if v},
        "isStock": bool(query.in_stock),
        "isOtherSuppliers": False,
        "isAsianBrand": False,
        "isDeals": False,
        "isEnvironment": False,
    }
    if not for_filters:
        payload.update({"currentPage": query.page, "pageSize": query.page_size})
        if query.sort_field:
            payload.update({"sortField": query.sort_field, "sortType": query.sort_dir})
    return payload


def unwrap(obj: Any) -> Any:
    if not isinstance(obj, dict):
        raise LCSCError("Unexpected API response type")
    if obj.get("code") not in (200, "200") or obj.get("ok") is False:
        raise LCSCError(
            f"LCSC API error {obj.get('code', '?')}: {val(obj.get('msg'), 'Unknown server error')}"
        )
    if obj.get("result") is None:
        raise LCSCError("LCSC returned an empty response")
    return obj["result"]


def parse_categories(raw: Any) -> list[Category]:
    def one(node: dict) -> Category:
        children = node.get("childrenList") or node.get("childCategoryList") or []
        return Category(
            id=int(node["categoryId"]),
            name=val(node.get("categoryNameEn") or node.get("categoryName")),
            children=tuple(
                one(n) for n in children if isinstance(n, dict) and n.get("categoryId") is not None
            ),
        )

    if not isinstance(raw, list):
        raise LCSCError("Unexpected categories response")
    return [one(n) for n in raw if isinstance(n, dict) and n.get("categoryId") is not None]


def parse_filters(raw: Any) -> list[FilterGroup]:
    if not isinstance(raw, dict):
        raise LCSCError("Unexpected filter groups response")
    groups: list[FilterGroup] = []
    for caption, key in (
        ("Manufacturer", "__manufacturer__"),
        ("Package", "__package__"),
        ("Packaging", "__packaging__"),
    ):
        options = []
        for node in raw.get(caption, []) or []:
            if isinstance(node, dict) and node.get("name"):
                ident = str(node.get("id")) if key == "__manufacturer__" else str(node["name"])
                if ident != "None":
                    options.append(Option(str(node["name"]), ident))
        if options:
            groups.append(FilterGroup(key, caption, tuple(options)))
    groups_by_name = raw.get("paramNameValueMap") or {}
    if isinstance(groups_by_name, dict):
        for name, entry in groups_by_name.items():
            if not isinstance(entry, dict):
                continue
            options = []
            for v in entry.get("paramDetailList", []) or []:
                if not isinstance(v, dict) or not v.get("name"):
                    continue
                # Preserve exact raw LCSC option name. The displayed range / units
                # are descriptive; no guessed unit conversion is sent in requests.
                options.append(
                    Option(
                        str(v["name"]),
                        str(v["name"]),
                        bool(v.get("isRange")),
                        None if v.get("standardUnitValue") is None else str(v["standardUnitValue"]),
                        None
                        if v.get("standardUnitEndValue") is None
                        else str(v["standardUnitEndValue"]),
                    )
                )
            if options:
                groups.append(
                    FilterGroup(
                        str(name),
                        str(name),
                        tuple(options),
                        tuple(str(v) for v in entry.get("unitList", []) or []),
                        entry.get("unitConversionMap") or {},
                    )
                )
    return groups


def parse_part(obj: dict, source: str, observed_at: str) -> Part:
    code = val(obj.get("productCode"))
    if not C_RE.fullmatch(code):
        raise LCSCError("Product has missing or invalid LCSC C-number")
    tiers = []
    for p in obj.get("productPriceList") or []:
        if not isinstance(p, dict):
            continue
        qty = integer(p.get("ladder"))
        amount = price_number(p.get("discountPrice"))
        if amount is None:
            amount = price_number(p.get("usdPrice"))
        if amount is None:
            amount = price_number(p.get("productPrice"))
        if qty is not None and amount is not None:
            currency = val(p.get("currencyType"), "")
            symbol = p.get("currencySymbol")
            if not currency:
                currency = "USD" if symbol in ("$", None) else "Unknown"
            tiers.append({"quantity": qty, "unit_price": amount, "currency": currency})
    specs = {}
    for a in obj.get("paramVOList") or []:
        if isinstance(a, dict):
            key = val(a.get("paramNameEn") or a.get("paramName"), "")
            value = val(a.get("paramValueEn") or a.get("paramValue"), "")
            if key and value:
                specs[key] = value
    attributes = obj.get("productKeyAttributes")
    if isinstance(attributes, dict):
        for key, value in attributes.items():
            if isinstance(value, (str, int, float)) and value not in ("", None):
                specs.setdefault(str(key), str(value))
    img = obj.get("productImageUrlBig") or obj.get("productImageUrl") or ""
    if not img and isinstance(obj.get("productImages"), list) and obj["productImages"]:
        first = obj["productImages"][0]
        img = (
            first
            if isinstance(first, str)
            else (first.get("url") if isinstance(first, dict) else "")
        )
    return Part(
        code=code,
        mpn=val(obj.get("productModel")),
        manufacturer=val(obj.get("brandNameEn")),
        package=val(obj.get("encapStandard")),
        description=val(
            obj.get("productIntroEn") or obj.get("productDescEn") or obj.get("productNameEn")
        ),
        category=val(obj.get("catalogName") or obj.get("wmCatalogNameEn")),
        product_id=integer(obj.get("productId")),
        stock=integer(obj.get("stockNumber")),
        image_url=img or "",
        datasheet_url=obj.get("pdfUrl") or obj.get("pdfLinkUrl") or "",
        product_url=obj.get("url") or f"https://www.lcsc.com/product-detail/{code}.html",
        price_tiers=sorted(tiers, key=lambda p: p["quantity"]),
        specs=specs,
        observed_at=observed_at,
        source=source,
    )


def parallel_queries(function, identities, cancel):
    from .cancellation import wait_future

    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lcsc-category")
    futures = [pool.submit(function, ident) for ident in identities]
    try:
        return [wait_future(future, cancel) for future in futures]
    finally:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)


def category_leaves(categories, category_id):
    """Resolve a visible category to its leaf IDs, retaining catalog order."""
    for category in categories:
        if category.id == category_id:

            def leaves(node):
                if not node.children:
                    return [node.id]
                return [item for child in node.children for item in leaves(child)]

            return tuple(dict.fromkeys(leaves(category)))
        found = category_leaves(category.children, category_id)
        if found:
            return found
    return ()


class LCSCBackend:
    def __init__(
        self,
        transport: Optional[Any] = None,
        cache: Optional[Cache] = None,
        cache_enabled: bool = True,
    ):
        self.transport = transport or Transport()
        self.cache = cache or Cache()
        self.cache_enabled = cache_enabled

    def _fetch(
        self,
        method: str,
        url: str,
        payload: Optional[dict] = None,
        ttl: int = 0,
        cancel: Optional[threading.Event] = None,
    ) -> Response:
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled")
        key = method + ":" + url + ":" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
        catalog_api = url.startswith(BASE + "/")
        if ttl and self.cache_enabled:
            hit = self.cache.get(key, ttl)
            if hit:
                try:
                    if catalog_api:
                        unwrap(hit.data)
                except LCSCError:
                    pass
                else:
                    return hit
        raw = self.transport.request(method, url, payload, cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled")
        observed = utc_now()
        if ttl and self.cache_enabled:
            if catalog_api:
                unwrap(raw)
            self.cache.put(key, raw)
        return Response(
            raw, "mocked" if getattr(self.transport, "is_mock", False) else "live-tested", observed
        )

    def categories(
        self, cancel: Optional[threading.Event] = None
    ) -> tuple[list[Category], Response]:
        r = self._fetch("GET", BASE + "/ftps/wm/product/category/tree", ttl=86400, cancel=cancel)
        return parse_categories(unwrap(r.data)), r

    def filter_groups(
        self, query: Query, cancel: Optional[threading.Event] = None
    ) -> tuple[list[FilterGroup], Response]:
        if len(query.category_ids) == 1:
            query = dataclasses.replace(query, category_id=query.category_ids[0], category_ids=())
        if len(query.category_ids) > 1:
            results = parallel_queries(
                lambda ident: self.filter_groups(
                    dataclasses.replace(query, category_id=ident, category_ids=()), cancel
                ),
                query.category_ids,
                cancel,
            )
            merged = {}
            for groups, _response in results:
                for group in groups:
                    original, options = merged.setdefault(group.key, (group, {}))
                    for option in group.options:
                        options.setdefault(option.value, option)
            groups = [
                dataclasses.replace(group, options=tuple(options.values()))
                for group, options in merged.values()
            ]
            return groups, Response({}, "combined category filters", utc_now())
        if query.category_id is None:
            return [], Response({}, "unverified", utc_now())
        r = self._fetch(
            "POST",
            BASE + "/ftps/wm/product/query/param/group",
            query_payload(query, for_filters=True),
            ttl=240,
            cancel=cancel,
        )
        return parse_filters(unwrap(r.data)), r

    def search(self, query: Query, cancel: Optional[threading.Event] = None) -> Page:
        if len(query.category_ids) == 1:
            query = dataclasses.replace(query, category_id=query.category_ids[0], category_ids=())
        if len(query.category_ids) > 1:
            return self.search_family(query, cancel)
        # Exact SKU means a true C-number lookup, never fuzzy prefix search.
        if (
            C_RE.fullmatch(query.keyword.strip())
            and query.category_id is None
            and not (
                query.attributes
                or query.manufacturers
                or query.packages
                or query.packaging
                or query.in_stock
            )
        ):
            p = self.exact(query.keyword.strip().upper(), cancel)
            return Page([p], 1, 1, 1, p.source, p.observed_at, "Exact LCSC C-number")
        r = self._fetch(
            "POST",
            BASE + "/ftps/wm/product/query/list",
            query_payload(query),
            ttl=45,
            cancel=cancel,
        )
        result = unwrap(r.data)
        if not isinstance(result, dict):
            raise LCSCError("Unexpected product search response")
        if (
            not result.get("dataList")
            and query.keyword.strip()
            and query.page == 1
            and query.category_id is None
            and not query.attributes
            and not query.manufacturers
            and not query.packages
            and not query.packaging
        ):
            return self.global_search(query, cancel)
        parts = []
        for o in result.get("dataList") or []:
            if isinstance(o, dict):
                try:
                    parts.append(parse_part(o, r.source, r.observed_at))
                except LCSCError:
                    continue
        count = integer(result.get("totalRow"))
        pages = integer(result.get("totalPage"))
        note = (
            "LCSC website API caps searchable results at 5,000; narrow filters for larger catalogs"
            if count == 5000
            else ""
        )
        return Page(
            parts,
            count,
            integer(result.get("currPage")) or query.page,
            pages,
            r.source,
            r.observed_at,
            note,
        )

    def search_family(self, query, cancel=None):
        """Browse every child category when the provider cannot query their parent/OR IDs."""

        def child(ident, page=1):
            return self.search(
                dataclasses.replace(query, category_id=ident, category_ids=(), page=page), cancel
            )

        identities = tuple(dict.fromkeys(query.category_ids))
        first = parallel_queries(child, identities, cancel)
        children = list(zip(identities, first))
        total = sum(page.total or len(page.parts) for _ident, page in children)
        offset = (query.page - 1) * query.page_size
        chosen = []
        if not query.sort_field:
            # Begin with populated categories, but retain every child's products/pages.
            for ident, initial in sorted(children, key=lambda pair: -(pair[1].total or 0)):
                count = initial.total or len(initial.parts)
                if offset >= count:
                    offset -= count
                    continue
                page_num = offset // query.page_size + 1
                skip = offset % query.page_size
                while len(chosen) < query.page_size:
                    page = initial if page_num == 1 else child(ident, page_num)
                    available = page.parts[skip:]
                    take = min(query.page_size - len(chosen), len(available))
                    chosen.extend(available[:take])
                    if (
                        len(chosen) == query.page_size
                        or not page.parts
                        or page_num >= (page.total_pages or 1)
                    ):
                        break
                    skip = 0
                    page_num += 1
                offset = 0
                if len(chosen) == query.page_size:
                    break
        else:

            def stream(ident, initial):
                yield from initial.parts
                for page_num in range(2, (initial.total_pages or 1) + 1):
                    yield from child(ident, page_num).parts

            def price(part):
                value = part.price_tiers[0].get("unit_price") if part.price_tiers else None
                if value is None or not math.isfinite(float(value)):
                    return float("inf")
                return -float(value) if query.sort_dir == "desc" else float(value)

            serial = itertools.count()
            heap = []
            for ident, initial in children:
                iterator = stream(ident, initial)
                part = next(iterator, None)
                if part:
                    heapq.heappush(heap, (price(part), next(serial), part, iterator))
            visited = 0
            while heap and len(chosen) < query.page_size:
                _price, _serial, part, iterator = heapq.heappop(heap)
                if visited >= offset:
                    chosen.append(part)
                visited += 1
                following = next(iterator, None)
                if following:
                    heapq.heappush(heap, (price(following), next(serial), following, iterator))
        observed = min((page.observed_at for page in first), default=utc_now())
        source = "cached" if all(page.source == "cached" for page in first) else "category browse"
        capped = any((page.total or 0) >= 5000 for page in first)
        note = f"Browsing {len(identities)} subcategories."
        if capped:
            note += " Supplier result limits apply; narrow filters for more results."
        return Page(
            chosen,
            total,
            query.page,
            max(1, (total + query.page_size - 1) // query.page_size),
            source,
            observed,
            note,
        )

    def global_search(self, query, cancel=None):
        """Website global search retains exact sold-out catalog matches omitted by query/list."""
        r = self._fetch(
            "POST", BASE + "/ftps/wm/search/v3/global", query_payload(query), ttl=45, cancel=cancel
        )
        result = unwrap(r.data)
        if not isinstance(result, dict):
            raise LCSCError("Unexpected global search response")
        listing = result.get("productSearchResultVO") or {}
        raw = list(result.get("exactMatchResult") or [])
        if isinstance(listing, dict):
            raw += list(listing.get("productList") or listing.get("dataList") or [])
        unique = {}
        for row in raw:
            if isinstance(row, dict):
                part = parse_part(row, r.source, r.observed_at)
                if not query.in_stock or (part.stock is not None and part.stock > 0):
                    unique[part.code] = part
        total = integer(result.get("totalCount"))
        if query.in_stock and total == len(
            {p.get("productCode") for p in raw if isinstance(p, dict)}
        ):
            total = len(unique)
        return Page(
            list(unique.values()),
            total,
            query.page,
            integer(result.get("productTotalPage")) or 1,
            r.source,
            r.observed_at,
            "LCSC global name search (includes unavailable catalog parts)",
        )

    def exact(self, lcsc_id: str, cancel: Optional[threading.Event] = None) -> Part:
        if not C_RE.fullmatch(lcsc_id):
            raise LCSCError("Expected exact LCSC number, e.g. C9864")
        url = f"https://www.lcsc.com/product-detail/{lcsc_id.upper()}.html"
        r = self._fetch("GET", url, ttl=60, cancel=cancel)
        if not isinstance(r.data, str):
            raise LCSCError("LCSC detail page returned non-HTML")
        match = NEXT_DATA_RE.search(r.data)
        if not match:
            raise LCSCError("No embedded product data found; detail page format may have changed")
        try:
            try:
                root = json.loads(match.group(1))
            except ValueError:
                root = json.loads(html.unescape(match.group(1)))
            page = root["props"]["pageProps"]
            if page.get("dataIsNull"):
                raise LCSCError(f"LCSC does not recognize {lcsc_id}")
            data = page["webData"]
        except (KeyError, ValueError, TypeError) as e:
            raise LCSCError("LCSC embedded product format changed") from e
        p = parse_part(data, r.source, r.observed_at)
        if p.code.upper() != lcsc_id.upper():
            raise LCSCError(f"Exact lookup mismatched: expected {lcsc_id}, got {p.code}")
        return p

    def details(self, part: Part, cancel: Optional[threading.Event] = None) -> Part:
        if part.product_id is None:
            return self.exact(part.code, cancel)
        params = urllib.parse.urlencode({"productCode": part.code, "productId": part.product_id})
        r = self._fetch("GET", BASE + "/ftps/wm/product/detail?" + params, ttl=60, cancel=cancel)
        p = parse_part(unwrap(r.data), r.source, r.observed_at)
        if p.code != part.code:
            raise LCSCError("Detail identity mismatch; rejected stale or incorrect result")
        return p

    def check_cad(self, part: Part, cancel: Optional[threading.Event] = None) -> Part:
        """Check symbol/footprint payload. STEP remains linked/unverified until fetched."""
        import copy

        r = self._fetch("GET", EASYEDA_API.format(part.code), ttl=900, cancel=cancel)
        envelope = r.data
        if not isinstance(envelope, dict):
            raise LCSCError("Invalid EasyEDA CAD result")
        if envelope.get("success") is False:
            # A clear 'not found' is different from a network failure.
            msg = str(envelope.get("message") or envelope.get("msg") or "")
            if any(w in msg.lower() for w in ("not found", "no component", "does not exist")):
                result = copy.deepcopy(part)
                result.cad_symbol = result.cad_footprint = result.cad_step = "confirmed unavailable"
                return result
            raise LCSCError("EasyEDA CAD lookup failed: " + (msg or "Unknown response"))
        cad = envelope.get("result")
        if not isinstance(cad, dict) or not cad:
            raise LCSCError("EasyEDA CAD response missing data; availability unknown")
        p = copy.deepcopy(part)
        # Normal EasyEDA part envelope contains a dataStr symbol and a packageDetail.
        p.cad_symbol = "confirmed metadata" if cad.get("dataStr") else "confirmed unavailable"
        package = cad.get("packageDetail")
        p.cad_footprint = (
            "confirmed metadata"
            if isinstance(package, dict) and package.get("dataStr")
            else "confirmed unavailable"
        )
        p.cad_step = (
            "confirmed unavailable" if p.cad_footprint == "confirmed unavailable" else "unchecked"
        )
        if isinstance(package, dict):
            raw = package.get("dataStr")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = None
            if isinstance(raw, dict):
                for shape in raw.get("shape") or []:
                    if not isinstance(shape, str) or not shape.startswith("SVGNODE~"):
                        continue
                    try:
                        attrs = json.loads(shape.split("~", 2)[1]).get("attrs", {})
                    except (ValueError, IndexError, AttributeError):
                        continue
                    uuid = attrs.get("uuid") if isinstance(attrs, dict) else None
                    if uuid and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", str(uuid)):
                        p.cad_step_uuid = str(uuid)
                        p.cad_step = "linked; file unverified"
                        break
                else:
                    p.cad_step = "confirmed unavailable"
        return p

    def verify_step(self, part: Part, cancel: Optional[threading.Event] = None) -> Part:
        import copy

        if not part.cad_step_uuid:
            raise LCSCError("STEP UUID has not been discovered; check CAD first")
        raw = self.transport.request(
            "GET", STEP_API.format(part.cad_step_uuid), cancel=cancel, max_bytes=2048, partial=True
        )
        p = copy.deepcopy(part)
        if not isinstance(raw, bytes) or b"ISO-10303-21" not in raw[:1024]:
            raise LCSCError(
                "STEP response is not a valid STEP header; availability remains unverified"
            )
        p.cad_step = "confirmed STEP header"
        return p

    def image(self, url: str, cancel: Optional[threading.Event] = None) -> bytes:
        # Do not connect to arbitrary URLs returned by remote content.
        if urllib.parse.urlparse(url).hostname != "assets.lcsc.com":
            raise LCSCError("Unsupported image host")
        return self.transport.request("GET", url, cancel=cancel, max_bytes=2 * 1024 * 1024)


class RequestGate:
    """Cooperative cancellation + generation check for UI async response suppression."""

    def __init__(self):
        self.versions: dict[str, int] = {}
        self.events: dict[str, threading.Event] = {}

    def begin(self, kind: str) -> tuple[int, threading.Event]:
        old = self.events.get(kind)
        if old is not None:
            old.set()
        version = self.versions.get(kind, 0) + 1
        self.versions[kind] = version
        event = threading.Event()
        self.events[kind] = event
        return version, event

    def current(self, kind: str, version: int, event: threading.Event) -> bool:
        return self.versions.get(kind) == version and not event.is_set()

    def cancel_all(self):
        for kind in list(self.events):
            self.begin(kind)
