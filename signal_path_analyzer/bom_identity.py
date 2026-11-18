"""Read-only supplier identity resolution for BOM costing; never substitutes parts."""

from __future__ import annotations

import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import component_schema as schema
from . import lcsc_research_backend as api
from .cancellation import OperationCancelled


def resolve(parts, cancel=None, progress=None, backend=None):
    backend = backend or api.LCSCBackend()
    copies = [dict(p, properties=dict(p.get("properties", {}))) for p in parts]
    pending = {}
    for part in copies:
        if part.get("dnp") or part.get("exclude_bom"):
            continue
        props = part["properties"]
        code = schema.properties(props).get("LCSC Part #", "")
        if re.fullmatch(r"C\d{2,}", code, re.I):
            continue
        provider, sku = schema.supplier_identity(props)
        if provider and provider != "LCSC" and sku:
            part["identity_source"] = f"saved {provider} order code; outside LCSC retail pricing"
            continue
        links = [
            str(v)
            for k, v in props.items()
            if any(x in k.casefold() for x in ("datasheet", "supplier", "lcsc", "url"))
        ]
        codes = set()
        for link in links:
            codes.update(
                re.findall(
                    r'https?://(?:www\.)?lcsc\.com/product-detail/(?:[^\s"<>]*_)?(C\d{2,})\.html',
                    link,
                    re.I,
                )
            )
        if len(codes) == 1:
            props["LCSC Part #"] = codes.pop().upper()
            part["identity_source"] = "saved LCSC product link; MPN checked at pricing"
            continue
        normalized = schema.properties(props)
        mpn = normalized.get("MPN", "")
        maker = normalized.get("Manufacturer", "")
        if mpn:
            pending.setdefault((mpn, maker), []).append(part)

    def search(identity):
        mpn, maker = identity
        page = backend.search(api.Query(keyword=mpn, page_size=100), cancel)
        exact = {p.code: p for p in page.parts if p.mpn.casefold() == mpn.casefold()}
        if len(exact) != 1:
            return (
                "",
                "no unique exact LCSC MPN match"
                if not exact
                else "multiple LCSC codes for exact MPN; select code in Components",
            )
        if page.total is None or page.total > len(page.parts):
            return "", "search truncated; select exact LCSC code in Components"
        part = next(iter(exact.values()))
        return (
            part.code,
            f"exact LCSC MPN search ({part.observed_at}); MPN checked again at pricing",
        )

    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bom-identity")
    futures = {pool.submit(search, identity): identity for identity in pending}
    index = 0
    try:
        while futures:
            if cancel and cancel.is_set():
                raise OperationCancelled("BOM identity lookup cancelled")
            done, _waiting = wait(futures, timeout=0.05, return_when=FIRST_COMPLETED)
            for future in done:
                identity = futures.pop(future)
                index += 1
                try:
                    code, note = future.result()
                except Exception as exc:
                    if cancel and cancel.is_set():
                        raise OperationCancelled("BOM identity lookup cancelled") from exc
                    code, note = "", "LCSC identity lookup unavailable: " + str(exc)
                for part in pending[identity]:
                    if code:
                        part["properties"]["LCSC Part #"] = code
                    part["identity_source"] = note
                if progress:
                    progress(index, len(pending), identity[0])
    finally:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
    return copies
