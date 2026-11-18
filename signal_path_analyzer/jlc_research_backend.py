"""JLCPCB assembly-parts research backend. No Qt dependency.

Uses independently observed JLCPCB website search and facet endpoints. This is
not a credentialed partner API. Stock, prices and library class remain separate
from LCSC retail observations. Basic/Extended filters were live verified during
integration on 18 November 2026; missing data remains Unknown.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE = "https://jlcpcb.com/api/overseas-pcb-order"
LIST_URL = BASE + "/v1/shoppingCart/smtGood/selectSmtComponentList/v2"
FACET_URL = BASE + "/v1/componentSearch/filterComponentAttribute"
EASYEDA_API = "https://easyeda.com/api/products/{}/components?version=6.4.19.5"
STEP_API = "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{}"
C_RE = re.compile(r"^C\d{2,}$", re.I)
MAX_BODY = 12 * 1024 * 1024


class JLCError(Exception):
    pass


class Cancelled(JLCError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text(value: Any, default="Unknown") -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def intval(value) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def floatval(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@dataclasses.dataclass(frozen=True)
class Category:
    id: int
    name: str
    children: tuple[Category, ...] = ()
    parent_id: int = 0
    parent_name: str = ""


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
    tier: str = "all"  # all, basic, preferred, extended (includes preferred)


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
    assembly_tier: str = "Unknown"
    raw_library_type: str = ""
    preferred: Optional[bool] = None
    min_purchase: Optional[int] = None
    min_placement: Optional[int] = None
    cad_symbol: str = "unchecked"
    cad_footprint: str = "unchecked"
    cad_step: str = "unchecked"
    cad_step_uuid: str = ""

    def cad_record(self):
        return {
            "source": "JLCPCB Assembly",
            "lcsc_id": self.code,
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "package": self.package,
            "assembly_tier": self.assembly_tier,
            "assembly_stock": self.stock,
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
    def __init__(self, root: Optional[Path] = None):
        self.root = (
            root or Path(os.environ.get("APPDATA", Path.home())) / "TraceForge/jlc-assembly-v1"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _path(self, key):
        return self.root / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key, max_age):
        try:
            with self.lock:
                obj = json.loads(self._path(key).read_text(encoding="utf8"))
            if time.time() - float(obj["epoch"]) <= max_age:
                return Response(obj["data"], "cached", obj["observed_at"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return None

    def put(self, key, data):
        obj = {"epoch": time.time(), "observed_at": utc_now(), "data": data}
        path = self._path(key)
        temp = path.with_suffix(".tmp")
        with self.lock:
            temp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)


class Transport:
    def __init__(self, timeout=9):
        self.timeout = max(1.0, min(20.0, float(timeout)))

    def request(self, method, url, payload=None, cancel=None, max_bytes=MAX_BODY, partial=False):
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled")
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = host in {
            "jlcpcb.com",
            "www.jlcpcb.com",
            "easyeda.com",
            "modules.easyeda.com",
            "assets.lcsc.com",
        }
        # JLCPCB may return signed media URLs on jlcpcb-controlled subdomains.
        allowed = allowed or host.endswith(".jlcpcb.com") or host.endswith(".lcsc.com")
        if parsed.scheme != "https" or not allowed:
            raise JLCError("Blocked external/unsafe URL host: " + host)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36",
            "Accept": "application/json, image/*;q=0.8, */*;q=0.5",
            "Accept-Encoding": "identity",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
            headers["Origin"] = "https://jlcpcb.com"
            headers["Referer"] = "https://jlcpcb.com/parts"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                # Avoid redirecting from a trusted image host to an arbitrary destination.
                dest = urllib.parse.urlparse(resp.geturl())
                final_host = (dest.hostname or "").lower()
                if not (
                    final_host
                    in {
                        "jlcpcb.com",
                        "www.jlcpcb.com",
                        "easyeda.com",
                        "modules.easyeda.com",
                        "assets.lcsc.com",
                    }
                    or final_host.endswith(".jlcpcb.com")
                    or final_host.endswith(".lcsc.com")
                ):
                    raise JLCError("Blocked redirect to unexpected host: " + final_host)
                chunks = bytearray()
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled("Cancelled")
                    remaining = max_bytes - len(chunks) if partial else max_bytes + 1 - len(chunks)
                    if partial and remaining <= 0:
                        break
                    chunk = resp.read(min(65536, max(1, remaining)))
                    if not chunk:
                        break
                    chunks += chunk
                    if len(chunks) > max_bytes:
                        raise JLCError("Response exceeds size limit")
        except urllib.error.HTTPError as exc:
            raise JLCError(
                f"JLCPCB HTTP {exc.code}; endpoint may have changed or blocked requests"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise JLCError(f"Network failure/timeout: {exc}") from exc
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled")
        if partial or host == "modules.easyeda.com" or "/images/" in parsed.path:
            return bytes(chunks)
        if (
            host not in {"jlcpcb.com", "www.jlcpcb.com", "easyeda.com"}
            and host != "modules.easyeda.com"
        ):
            return bytes(chunks)
        try:
            return json.loads(chunks.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise JLCError("Response is not valid JSON; website API may have changed") from exc


def unwrap(obj):
    if not isinstance(obj, dict):
        raise JLCError("Expected JSON object")
    if obj.get("code") not in (200, "200"):
        message = text(obj.get("message") or obj.get("msg"), "Unknown error")
        raise JLCError(f"JLCPCB rejected request: {message} (code={obj.get('code')})")
    if not isinstance(obj.get("data"), dict):
        raise JLCError("JLCPCB response lacks data object")
    return obj["data"]


def category_tree(data):
    raw = data.get("sortAndCountVoList") or data.get("categories") or []
    if not isinstance(raw, list):
        raise JLCError("Unexpected JLCPCB category tree")

    def parse(node, parent_id=0, parent_name=""):
        if not isinstance(node, dict):
            return None
        cid = intval(node.get("componentSortKeyId"))
        name = text(node.get("sortName"), "")
        if not name or cid is None:
            return None
        children = tuple(
            c for x in (node.get("childSortList") or []) if (c := parse(x, cid, name)) is not None
        )
        return Category(cid, name, children, parent_id, parent_name)

    return [n for x in raw if (n := parse(x)) is not None]


def parse_filters(data):
    if not isinstance(data, dict):
        raise JLCError("Invalid facet response")
    groups = []
    for key, title, src in (
        ("__package__", "Package", "componentSpecificationList"),
        ("__manufacturer__", "Manufacturer", "componentBrandList"),
    ):
        candidates = data.get(src) or []
        options = tuple(
            Option(str(o["name"]), str(o["name"]))
            for o in candidates
            if isinstance(o, dict) and o.get("name")
        )
        if options:
            groups.append(FilterGroup(key, title, options))
    # At leaf level the API often returns parentParamRangeList rather than paramRangeList.
    ranges = data.get("paramRangeList") or data.get("parentParamRangeList") or []
    for group in ranges:
        if not isinstance(group, dict) or not group.get("name"):
            continue
        name = str(group["name"])
        options = []
        for entry in group.get("subAggs") or []:
            if isinstance(entry, dict) and entry.get("name"):
                label = str(entry["name"])
                start = entry.get("intervalStartValue")
                end = entry.get("intervalEndValue")
                options.append(
                    Option(
                        label,
                        label,
                        bool(start is not None or end is not None),
                        None if start is None else str(start),
                        None if end is None else str(end),
                    )
                )
        if options:
            groups.append(FilterGroup(name, name, tuple(options)))
    return groups


def tier_of(raw, preferred):
    if raw == "base":
        return "Basic"
    if raw == "expand":
        return "Preferred Extended" if preferred is True else "Extended"
    return "Unknown"


def tier_matches(part, tier):
    return (
        tier == "all"
        or (tier == "basic" and part.assembly_tier == "Basic")
        or (tier == "preferred" and part.assembly_tier == "Preferred Extended")
        or (tier == "extended" and part.assembly_tier in ("Extended", "Preferred Extended"))
    )


def parse_part(obj, source, observed_at):
    code = text(obj.get("componentCode"), "")
    if not C_RE.fullmatch(code):
        raise JLCError("Invalid/missing JLCPCB part C-number")
    prices = []
    for level in obj.get("componentPrices") or []:
        if not isinstance(level, dict):
            continue
        qty = intval(level.get("startNumber"))
        amount = floatval(level.get("productPrice"))
        if qty is not None and amount is not None:
            # The componentPrices ladder is USD per the independent client contract.
            prices.append({"quantity": qty, "unit_price": amount, "currency": "USD"})
    specs = {}
    for attr in obj.get("attributes") or []:
        if isinstance(attr, dict):
            name = text(attr.get("attribute_name_en") or attr.get("attributeName"), "")
            value = text(attr.get("attribute_value_name") or attr.get("attributeValue"), "")
            if name and value and value != "-":
                specs[name] = value
    raw_type = text(obj.get("componentLibraryType"), "")
    preferred = obj.get("preferredComponentFlag")
    if not isinstance(preferred, bool):
        preferred = None
    image = (
        obj.get("minImageAccessIdUrl")
        or obj.get("productBigImageAccessIdUrl")
        or obj.get("componentImageUrl")
        or obj.get("minImage")
        or ""
    )
    datasheet = (
        obj.get("dataManualFileAccessIdUrl")
        or obj.get("dataManualUrl")
        or obj.get("dataManualOfficialLink")
        or ""
    )
    return Part(
        code=code.upper(),
        mpn=text(obj.get("componentModelEn")),
        manufacturer=text(obj.get("componentBrandEn")),
        package=text(obj.get("componentSpecificationEn")),
        description=text(obj.get("describe") or obj.get("componentName")),
        category=text(obj.get("componentTypeEn") or obj.get("firstSortName")),
        product_id=intval(obj.get("componentId")),
        stock=intval(obj.get("stockCount")),
        image_url=image,
        datasheet_url=datasheet,
        product_url=f"https://jlcpcb.com/partdetail/{code.upper()}",
        price_tiers=sorted(prices, key=lambda x: x["quantity"]),
        specs=specs,
        source=source,
        observed_at=observed_at,
        assembly_tier=tier_of(raw_type, preferred),
        raw_library_type=raw_type,
        preferred=preferred,
        min_purchase=intval(obj.get("minPurchaseNum")),
        min_placement=intval(obj.get("leastPatchNumber")),
    )


def tier_payload(tier):
    if tier == "all":
        return {}
    if tier == "basic":
        return {"componentLibraryType": "base", "componentLibTypes": ["base"]}
    if tier == "preferred":
        return {"preferredComponentFlag": True}
    if tier == "extended":
        return {"componentLibTypes": ["expand"]}
    raise JLCError("Invalid assembly class selected")


def search_payload(query, category=None):
    if not (1 <= query.page_size <= 100) or query.page < 1:
        raise JLCError("Invalid page or page size")
    if query.sort_field not in {"", "price", "stock"} or query.sort_dir not in {"asc", "desc"}:
        raise JLCError("Unsupported sort selection")
    body = {
        "currentPage": query.page,
        "pageSize": query.page_size,
        "keyword": query.keyword.strip(),
        "searchSource": "search",
        "searchType": 3,
        "stockFlag": bool(query.in_stock),
        "stockSort": None,
        "sortMode": {"": "", "price": "PRICE_SORT", "stock": "STOCK_SORT"}[query.sort_field],
        "sortASC": query.sort_dir if query.sort_field else "",
        "componentBrandList": list(query.manufacturers),
        "componentSpecificationList": list(query.packages),
        "componentAttributeList": [{k: list(v)} for k, v in sorted(query.attributes.items()) if v],
        "paramList": [],
        "startStockNumber": None,
    }
    body.update(tier_payload(query.tier))
    if category is not None:
        if category.parent_id:
            body.update(
                {
                    "firstSortId": category.parent_id,
                    "firstSortName": category.parent_name,
                    "firstSortNameNew": category.parent_name,
                    "secondSortId": category.id,
                    "secondSortName": category.name,
                    "secondSortNameNew": category.name,
                }
            )
        else:
            body.update(
                {
                    "firstSortId": category.id,
                    "firstSortName": category.name,
                    "firstSortNameNew": category.name,
                }
            )
    return body


def facet_payload(query, category):
    body = {
        "baseQueryDto": {
            "componentBrandList": list(query.manufacturers),
            "componentSpecificationList": list(query.packages),
            "componentTypeIdList": [category.id] if category.parent_id else [],
            "productTypeIdList": [category.parent_id or category.id],
            "orderLibraryTypeList": (
                {"all": [], "basic": ["base"], "preferred": [], "extended": ["expand"]}[query.tier]
            ),
            "preferredComponentFlag": True if query.tier == "preferred" else None,
            "packageTypeList": [],
            "filterType": 1,
            "keyword": query.keyword.strip() or None,
            "queryShelveStatus": None,
        },
        "catalogLevel": 2 if category.parent_id else 1,
        "nowCondition": "",
        "paramList": [{k: list(v)} for k, v in sorted(query.attributes.items()) if v],
        "queryString": query.keyword.strip(),
    }
    return body


class JLCBackend:
    def __init__(self, transport=None, cache=None, cache_enabled=True):
        self.transport = transport or Transport()
        self.cache = cache or Cache()
        self.cache_enabled = cache_enabled
        self._categories: dict[int, Category] = {}
        self._cat_lock = threading.Lock()

    def _fetch(self, method, url, payload=None, ttl=0, cancel=None):
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled")
        key = method + ":" + url + ":" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if self.cache_enabled and ttl:
            hit = self.cache.get(key, ttl)
            if hit:
                return hit
        data = self.transport.request(method, url, payload, cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled")
        observed = utc_now()
        if self.cache_enabled and ttl:
            self.cache.put(key, data)
        return Response(
            data, "mocked" if getattr(self.transport, "is_mock", False) else "live-tested", observed
        )

    def categories(self, cancel=None):
        # JLCPCB supplies the category tree in searchType=3 search responses.
        r = self._fetch(
            "POST",
            LIST_URL,
            search_payload(Query(keyword="", page_size=10)),
            ttl=3600,
            cancel=cancel,
        )
        categories = category_tree(unwrap(r.data))
        if not categories:
            raise JLCError(
                "Search response did not contain a category tree. Cannot show categories safely."
            )
        by_id = {}

        def collect(items):
            for item in items:
                by_id[item.id] = item
                collect(item.children)

        collect(categories)
        with self._cat_lock:
            self._categories = by_id
        return categories, r

    def _category(self, id):
        if id is None:
            return None
        with self._cat_lock:
            found = self._categories.get(id)
        if found is None:
            raise JLCError("Category metadata not yet loaded. Reload categories and retry.")
        return found

    def filter_groups(self, query, cancel=None):
        if query.category_id is None:
            return [], Response({}, "unverified", utc_now())
        category = self._category(query.category_id)
        r = self._fetch("POST", FACET_URL, facet_payload(query, category), ttl=300, cancel=cancel)
        return parse_filters(unwrap(r.data)), r

    def search(self, query, cancel=None):
        category = self._category(query.category_id)
        exact = C_RE.fullmatch(query.keyword.strip()) and category is None
        r = self._fetch("POST", LIST_URL, search_payload(query, category), ttl=40, cancel=cancel)
        info = unwrap(r.data).get("componentPageInfo")
        if not isinstance(info, dict):
            raise JLCError("Missing componentPageInfo in search response")
        raw = info.get("list")
        if not isinstance(raw, list):
            raise JLCError("Missing list in componentPageInfo")
        parts = []
        for obj in raw:
            if isinstance(obj, dict):
                try:
                    p = parse_part(obj, r.source, r.observed_at)
                    if exact and p.code.upper() != query.keyword.strip().upper():
                        continue
                    # Classification mismatch is an API contract violation, not a
                    # result to silently hide and paginate incorrectly.
                    if not tier_matches(p, query.tier):
                        raise JLCError(
                            f"Server ignored tier filter: {query.tier}; "
                            f"returned {p.code} ({p.assembly_tier})"
                        )
                    if query.in_stock and p.stock is not None and p.stock <= 0:
                        raise JLCError(f"Server ignored in-stock filter: {p.code} has {p.stock}")
                    parts.append(p)
                except JLCError as exc:
                    if "missing JLCPCB part" in str(exc) or "Invalid/missing" in str(exc):
                        continue
                    raise
        total = intval(info.get("total"))
        pages = intval(info.get("pages"))
        note = "Exact C-number search; only exact identity shown. " if exact else ""
        if exact and total is not None and len(parts) != total:
            total = len(parts)
            pages = 1
        return Page(
            parts,
            total,
            intval(info.get("pageNum")) or query.page,
            pages,
            r.source,
            r.observed_at,
            note + "JLCPCB assembly inventory; never LCSC retail stock",
        )

    def exact(self, lcsc_id, cancel=None):
        if not C_RE.fullmatch(lcsc_id):
            raise JLCError("Enter a valid C-number")
        page = self.search(Query(keyword=lcsc_id.upper(), page_size=20), cancel)
        for part in page.parts:
            if part.code.upper() == lcsc_id.upper():
                return part
        raise JLCError("Exact C-number not found in JLCPCB assembly catalog")

    def details(self, part, cancel=None):
        # Query by code instead of using undocumented detail endpoint assumptions.
        # Reuses the exact identity and current live stock observation.
        try:
            return self.exact(part.code, cancel)
        except JLCError as exc:
            raise JLCError(f"Cannot refresh details for {part.code}: {exc}") from exc

    def check_cad(self, part, cancel=None):
        r = self._fetch("GET", EASYEDA_API.format(part.code), ttl=600, cancel=cancel)
        envelope = r.data
        if not isinstance(envelope, dict):
            raise JLCError("Invalid EasyEDA response")
        if envelope.get("success") is False:
            raise JLCError("EasyEDA returned failure; CAD availability remains unchecked")
        cad = envelope.get("result")
        if not isinstance(cad, dict) or not cad:
            raise JLCError("No CAD result metadata; availability unknown")
        out = copy.deepcopy(part)
        out.cad_symbol = "confirmed metadata" if cad.get("dataStr") else "confirmed unavailable"
        package = cad.get("packageDetail")
        out.cad_footprint = (
            "confirmed metadata"
            if isinstance(package, dict) and package.get("dataStr")
            else "confirmed unavailable"
        )
        out.cad_step = "unchecked"
        if isinstance(package, dict):
            shape = package.get("dataStr")
            if isinstance(shape, str):
                try:
                    shape = json.loads(shape)
                except ValueError:
                    shape = None
            if isinstance(shape, dict):
                for node in shape.get("shape") or []:
                    if not isinstance(node, str) or not node.startswith("SVGNODE~"):
                        continue
                    try:
                        attrs = json.loads(node.split("~", 2)[1]).get("attrs", {})
                        uuid = attrs.get("uuid") if isinstance(attrs, dict) else None
                    except (ValueError, IndexError):
                        continue
                    if uuid and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", str(uuid)):
                        out.cad_step_uuid = str(uuid)
                        out.cad_step = "linked; file unverified"
                        break
        return out

    def verify_step(self, part, cancel=None):
        if not part.cad_step_uuid:
            raise JLCError("Check CAD first to discover STEP model UUID")
        raw = self.transport.request(
            "GET", STEP_API.format(part.cad_step_uuid), cancel=cancel, max_bytes=2048, partial=True
        )
        if not isinstance(raw, bytes) or b"ISO-10303-21" not in raw[:1024]:
            raise JLCError("STEP header not verified; availability still unknown")
        out = copy.deepcopy(part)
        out.cad_step = "confirmed STEP header"
        return out

    def image(self, url, cancel=None):
        # Signed JLCPCB links may expire; fetch when selected.
        return self.transport.request(
            "GET", url, cancel=cancel, max_bytes=2 * 1024 * 1024, partial=True
        )


class RequestGate:
    """Cooperative cancellation, generation IDs block stale worker response."""

    def __init__(self):
        self.versions = {}
        self.events = {}

    def begin(self, kind):
        old = self.events.get(kind)
        if old is not None:
            old.set()
        version = self.versions.get(kind, 0) + 1
        self.versions[kind] = version
        event = threading.Event()
        self.events[kind] = event
        return version, event

    def current(self, kind, version, event):
        return self.versions.get(kind) == version and not event.is_set()

    def cancel_all(self):
        for kind in list(self.events):
            self.begin(kind)
