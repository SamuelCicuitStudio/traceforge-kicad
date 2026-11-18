"""LCSC retail acquisition adapted from the user's EasyEDA_LCSC_All_In_One.py.
Retail observations are not JLCPCB assembly inventory or a supplier quotation.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from html import unescape as html_unescape
from typing import Any, Callable

from .cancellation import OperationCancelled

_network_state = threading.local()


@contextmanager
def cancel_requests(event):
    previous = getattr(_network_state, "cancel", None)
    _network_state.cancel = event
    try:
        yield
    finally:
        _network_state.cancel = previous


def check_cancelled():
    event = getattr(_network_state, "cancel", None)
    if event is not None and event.is_set():
        raise OperationCancelled("BOM pricing cancelled")


def read_response(response, maximum):
    if getattr(_network_state, "cancel", None) is None:
        return response.read(maximum + 1)
    data = bytearray()
    while len(data) <= maximum:
        check_cancelled()
        chunk = response.read(min(65536, maximum + 1 - len(data)))
        if not chunk:
            break
        data += chunk
    check_cancelled()
    return bytes(data)


class LookupError(Exception):
    pass


LCSC_DETAIL = "https://wmsc.lcsc.com/ftps/wm/product/detail"
LCSC_PRODUCT = "https://www.lcsc.com/product-detail/{lcsc}.html"
LCSC_QUERY = "https://wmsc.lcsc.com/ftps/wm/product/query/list"
MAX_JSON = 16 * 1024 * 1024
MAX_HTML = 9 * 1024 * 1024
NEXT_DATA_PATTERN = re.compile(
    r"<script\b[^>]*\bid=[\'\"]__NEXT_DATA__[\'\"][^>]*>(.*?)</script>", re.I | re.S
)


def network_open(url: str, *, timeout: int = 25, method: str = "GET", payload: Any = None):
    """Fixed provider endpoints only. Never call this on arbitrary file URLs."""
    check_cancelled()
    if getattr(_network_state, "cancel", None) is not None:
        timeout = min(timeout, 8)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Encoding": "identity",
        "Referer": "https://www.lcsc.com/"
        if urllib.parse.urlsplit(url).hostname in {"wmsc.lcsc.com", "www.lcsc.com"}
        else "https://easyeda.com/",
    }
    if body is not None:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raise LookupError(
            f"HTTP {error.code} from {urllib.parse.urlsplit(url).hostname}; "
            "service may be blocked or unavailable"
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LookupError(
            f"Network error from {urllib.parse.urlsplit(url).hostname}: {error}"
        ) from error


def fetch_json(
    url: str, *, max_bytes: int = MAX_JSON, method: str = "GET", payload: Any = None
) -> dict:
    with network_open(url, method=method, payload=payload) as response:
        raw = read_response(response, max_bytes)
    if len(raw) > max_bytes:
        raise LookupError("Server response exceeds the safety limit")
    try:
        item = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as error:
        raise LookupError("Provider returned non-JSON data (possible access block)") from error
    if not isinstance(item, dict):
        raise LookupError("Provider returned an unexpected data format")
    return item


def _validate_detail(item: Any, lcsc: str) -> dict:
    if not isinstance(item, dict):
        raise LookupError("LCSC did not return a product record")
    returned_code = str(item.get("productCode", "")).upper()
    if returned_code != lcsc:
        raise LookupError(
            f"Unexpected LCSC product code: {returned_code or '(missing)'} (expected {lcsc})"
        )
    if not any(key in item for key in ("stockNumber", "productPriceList", "productModel")):
        raise LookupError("LCSC product record lacks stock/pricing fields")
    return item


def _lcsc_direct(lcsc: str, product_id: Any = None) -> dict:
    params: dict[str, str] = {"productCode": lcsc}
    if product_id is not None:
        params["productId"] = str(product_id)
    payload = fetch_json(LCSC_DETAIL + "?" + urllib.parse.urlencode(params))
    if str(payload.get("code")) != "200" or not isinstance(payload.get("result"), dict):
        raise LookupError(
            str(
                payload.get("msg")
                or payload.get("message")
                or "LCSC detail endpoint rejected the query"
            )
        )
    return _validate_detail(payload["result"], lcsc)


def _lcsc_html(lcsc: str) -> dict:
    url = LCSC_PRODUCT.format(lcsc=lcsc)
    with network_open(url, timeout=30) as response:
        html_data = read_response(response, MAX_HTML)
    if len(html_data) > MAX_HTML:
        raise LookupError("LCSC HTML page exceeds safety limit")
    html_text = html_data.decode("utf-8", errors="replace")
    match = NEXT_DATA_PATTERN.search(html_text)
    if not match:
        raise LookupError("LCSC HTML has no __NEXT_DATA__ JSON (site may have changed)")
    try:
        body = json.loads(html_unescape(match.group(1)))
        page_props = body["props"]["pageProps"]
        if page_props.get("dataIsNull"):
            raise LookupError("LCSC reports that the component does not exist")
        item = page_props["webData"]
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise LookupError("Cannot decode LCSC product HTML data") from error
    return _validate_detail(item, lcsc)


def _lcsc_search_product_id(lcsc: str) -> Any:
    """Fallback if both code-only detail and product-page HTML are unavailable."""
    body = {
        "keyword": lcsc,
        "currentPage": 1,
        "pageSize": 20,
        "catalogIdList": [],
        "brandIdList": [],
        "encapValueList": [],
        "isStock": False,
        "paramNameValueMap": {},
    }
    data = fetch_json(LCSC_QUERY, method="POST", payload=body)
    if str(data.get("code")) != "200":
        raise LookupError("LCSC component search rejected the request")
    result = data.get("result")
    rows = result.get("dataList") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise LookupError("LCSC component search did not return a product list")
    for row in rows:
        if isinstance(row, dict) and str(row.get("productCode", "")).upper() == lcsc:
            product_id = row.get("productId")
            if product_id is not None:
                return product_id
    raise LookupError(f"LCSC search did not identify productId for {lcsc}")


def _as_nonneg_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    from decimal import Decimal, InvalidOperation

    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            return None
        return int(number)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _as_positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not (0 < number < 1e12):
        return None
    return number


def normalize_pricing(item: dict, lcsc: str, source: str) -> dict:
    """Keep null distinct from 0 stock; only quote genuine USD price fields."""
    prices = []
    raw = item.get("productPriceList")
    if isinstance(raw, list):
        for record in raw:
            if not isinstance(record, dict):
                continue
            qty = _as_nonneg_int(record.get("ladder"))
            cost = _as_positive_number(record.get("usdPrice"))
            if qty is None or qty == 0 or cost is None:
                continue
            prices.append({"min_quantity": qty, "unit_price_usd": cost})
    prices.sort(key=lambda p: p["min_quantity"])
    # More than one record for a threshold: keep one (first from the provider).
    seen = set()
    prices = [p for p in prices if not (p["min_quantity"] in seen or seen.add(p["min_quantity"]))]
    utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "lcsc_code": lcsc,
        "supplier": "LCSC",
        "inventory_type": "LCSC retail stock (NOT JLCPCB assembly stock)",
        "retrieved_at_utc": utc,
        "source": source,
        "product_url": LCSC_PRODUCT.format(lcsc=lcsc),
        "mpn": str(item.get("productModel") or ""),
        "manufacturer": str(item.get("brandNameEn") or ""),
        "package": str(item.get("encapStandard") or ""),
        "description": str(item.get("productIntroEn") or ""),
        "stock": _as_nonneg_int(item.get("stockNumber")),
        "minimum_order": _as_nonneg_int(item.get("minBuyNumber")),
        "quantity_schema": 2,
        "order_multiple": _as_nonneg_int(item.get("split")),
        "datasheet": str(item.get("pdfUrl") or ""),
        "price_tiers_usd": prices,
    }


def lookup_pricing(lcsc: str, log: Callable[[str], None]) -> dict:
    """Try direct JSON, then product-page JSON, then search->detail."""
    lcsc = lcsc.upper()
    if not re.fullmatch(r"C[0-9]{2,}", lcsc):
        raise LookupError("Invalid LCSC code")
    errors = []
    try:
        log("LCSC retail: requesting live product JSON ...")
        return normalize_pricing(_lcsc_direct(lcsc), lcsc, "LCSC product/detail JSON")
    except (LookupError, OSError) as error:
        errors.append(f"direct: {error}")
        log("LCSC direct endpoint unavailable; trying product-page data ...")
    try:
        return normalize_pricing(_lcsc_html(lcsc), lcsc, "LCSC product-page __NEXT_DATA__")
    except (LookupError, OSError) as error:
        errors.append(f"HTML: {error}")
        log("LCSC page data unavailable; trying product ID search ...")
    try:
        product_id = _lcsc_search_product_id(lcsc)
        return normalize_pricing(
            _lcsc_direct(lcsc, product_id), lcsc, "LCSC search + product/detail JSON"
        )
    except (LookupError, OSError) as error:
        errors.append(f"search: {error}")
    raise LookupError(
        "Live LCSC pricing and stock are UNAVAILABLE. No prices were estimated.\n"
        + "\n".join(errors)
    )
