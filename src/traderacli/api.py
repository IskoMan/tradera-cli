"""Thin read-only client for the official Tradera API.

Search goes through SOAP v3 SearchService.SearchAdvanced: it is stable and fully
typed in the WSDL, while the REST v4 search schemas are still empty (beta).
Item details and reference data go through REST v4, which documents those.

Credentials (free developer account, https://api.tradera.com/register):
env TRADERA_APP_ID / TRADERA_APP_KEY, else ~/.config/tradera-cli/env (KEY=VALUE lines).
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import httpx

REST_URL = "https://api.tradera.com/v4"
SOAP_URL = "https://api.tradera.com/v3/SearchService.asmx"
NS = "http://api.tradera.com"
CONFIG_FILE = Path.home() / ".config" / "tradera-cli" / "env"

# SearchAdvancedRequest fields in WSDL sequence order. The schema is a strict
# xs:sequence, so elements must be emitted in exactly this order.
ADVANCED_FIELDS = [
    "SearchWords", "CategoryId", "SearchInDescription", "Mode", "PriceMinimum",
    "PriceMaximum", "BidsMinimum", "BidsMaximum", "ZipCode", "CountyId", "Alias",
    "OrderBy", "ItemStatus", "ItemType", "OnlyAuctionsWithBuyNow",
    "OnlyItemsWithThumbnail", "ItemsPerPage", "PageNumber", "ItemCondition", "SellerType",
]

# String enums are undocumented in the WSDL. These were probed against the live
# API 2026-09-28: every value below filters, anything else returns a
# *ValidationError. OrderBy/Mode/ItemStatus also reject unknown values.
ORDER_BY = [
    "Relevance", "PriceAscending", "PriceDescending", "EndDateAscending",
    "EndDateDescending", "BidsAscending", "BidsDescending",
]
ITEM_TYPES = ["All", "Auction", "BuyItNow"]
ITEM_CONDITIONS = ["All", "OnlyNew", "OnlySecondHand"]
SELLER_TYPES = ["All", "Private", "Company"]


class CredentialsMissing(RuntimeError):
    pass


def credentials() -> tuple[str, str]:
    app_id, app_key = os.environ.get("TRADERA_APP_ID"), os.environ.get("TRADERA_APP_KEY")
    if not (app_id and app_key) and CONFIG_FILE.exists():
        vals = dict(
            line.split("=", 1)
            for line in CONFIG_FILE.read_text().splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        )
        app_id = app_id or vals.get("TRADERA_APP_ID", "").strip()
        app_key = app_key or vals.get("TRADERA_APP_KEY", "").strip()
    if not (app_id and app_key):
        raise CredentialsMissing(
            "no Tradera credentials: register at https://api.tradera.com/register, "
            f"then put TRADERA_APP_ID=... and TRADERA_APP_KEY=... in {CONFIG_FILE}"
        )
    return app_id, app_key


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(60, connect=10),
        # Force IPv4: the dev machine's IPv6 default route is black-holed and httpx has no
        # happy-eyeballs, so an AAAA-first answer stalls every connect.
        transport=httpx.HTTPTransport(local_address="0.0.0.0"),
    )


def _xml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return escape(str(v))


def build_envelope(app_id: str, app_key: str, request: dict[str, Any]) -> str:
    unknown = set(request) - set(ADVANCED_FIELDS)
    if unknown:
        raise ValueError(f"unknown SearchAdvanced fields: {sorted(unknown)}")
    fields = "".join(
        f"<{k}>{_xml_value(request[k])}</{k}>"
        for k in ADVANCED_FIELDS
        if request.get(k) is not None
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Header>"
        f'<AuthenticationHeader xmlns="{NS}"><AppId>{escape(app_id)}</AppId>'
        f"<AppKey>{escape(app_key)}</AppKey></AuthenticationHeader>"
        f'<ConfigurationHeader xmlns="{NS}"><Sandbox>0</Sandbox>'
        "<MaxResultAge>0</MaxResultAge></ConfigurationHeader>"
        "</soap:Header>"
        f'<soap:Body><SearchAdvanced xmlns="{NS}"><request>{fields}</request>'
        "</SearchAdvanced></soap:Body></soap:Envelope>"
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _to_dict(el: ET.Element) -> Any:
    kids = list(el)
    if not kids:
        return el.text
    out: dict[str, Any] = {}
    for k in kids:
        name, val = _local(k.tag), _to_dict(k)
        if name in out:  # repeated element -> list
            if not isinstance(out[name], list):
                out[name] = [out[name]]
            out[name].append(val)
        else:
            out[name] = val
    return out


def parse_search_response(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    fault = next((e for e in root.iter() if _local(e.tag) == "Fault"), None)
    if fault is not None:
        msg = next((e.text for e in fault.iter() if _local(e.tag) == "faultstring"), "")
        raise RuntimeError(f"SOAP fault: {msg}")
    result = next(e for e in root.iter() if _local(e.tag) == "SearchAdvancedResult")
    items = [_to_dict(e) for e in result if _local(e.tag) == "Items"]
    errors = [_to_dict(e) for e in result if _local(e.tag) == "Errors"]
    if errors:
        raise RuntimeError(f"search errors: {errors}")

    def num(tag: str) -> int:
        el = next((e for e in result if _local(e.tag) == tag), None)
        return int(el.text) if el is not None and el.text else 0

    return {
        "total_items": num("TotalNumberOfItems"),
        "total_pages": num("TotalNumberOfPages"),
        "items": items,
    }


def search_page(request: dict[str, Any], client: httpx.Client | None = None) -> dict[str, Any]:
    app_id, app_key = credentials()
    c = client or _client()
    try:
        resp = c.post(
            SOAP_URL,
            content=build_envelope(app_id, app_key, request).encode(),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{NS}/SearchAdvanced"',
            },
        )
        if resp.status_code >= 400 and b"Fault" not in resp.content:
            resp.raise_for_status()
        return parse_search_response(resp.text)
    finally:
        if client is None:
            c.close()


def search(
    request: dict[str, Any], max_pages: int = 1, client: httpx.Client | None = None
) -> Iterator[dict[str, Any]]:
    """Yield items across pages (Tradera pages are 1-based)."""
    c = client or _client()
    try:
        page = 1
        while page <= max_pages:
            data = search_page({**request, "PageNumber": page}, client=c)
            yield from data["items"]
            if page >= data["total_pages"]:
                break
            page += 1
    finally:
        if client is None:
            c.close()


def rest_get(path: str, client: httpx.Client | None = None, **params: Any) -> Any:
    app_id, app_key = credentials()
    c = client or _client()
    try:
        resp = c.get(
            f"{REST_URL}{path}",
            params=params or None,
            headers={"X-App-Id": app_id, "X-App-Key": app_key},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if client is None:
            c.close()
