"""tradera — search tradera.se from the terminal via the official Tradera API."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import api


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def price(item: dict[str, Any]) -> int:
    """What it costs right now: Buy Now if set, else the next bid."""
    return _int(item.get("BuyItNowPrice")) or _int(item.get("NextBid")) or _int(item.get("MaxBid"))


def format_item(item: dict[str, Any]) -> str:
    p = price(item)
    amount = f"{p:,}".replace(",", " ") + " kr" if p else "—"
    buy_now = _int(item.get("BuyItNowPrice"))
    if item.get("ItemType") == "ShopItem":
        kind = "butik"
    elif buy_now and not _int(item.get("BidCount")):
        kind = "köp nu"
    else:
        kind = f"{_int(item.get('BidCount'))} bud"
    end = (item.get("EndDate") or "?")[:16].replace("T", " ")
    return (
        f"{amount:>10}  {kind:<8} ends {end}  {item.get('ShortDescription', '?')}\n"
        f"{'':>12}{item.get('ItemUrl', '')}"
    )


def cmd_search(args: argparse.Namespace) -> int:
    request = {
        "SearchWords": args.query,
        "SearchInDescription": args.in_description or None,
        "PriceMinimum": args.min_price,
        "PriceMaximum": args.max_price,
        "CategoryId": args.category,
        "CountyId": args.county,
        "ZipCode": args.zip,
        "OrderBy": args.sort,
        "ItemType": args.type,
        "ItemCondition": args.condition,
        "SellerType": args.seller,
        "ItemsPerPage": args.per_page,
        "ItemStatus": "Ended" if args.ended else None,
    }
    items = list(api.search(request, max_pages=args.pages))
    if args.limit:
        items = items[: args.limit]
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for it in items:
            print(format_item(it))
        print(f"\n{len(items)} results", file=sys.stderr)
    return 0


def cmd_item(args: argparse.Namespace) -> int:
    print(json.dumps(api.rest_get(f"/items/{args.id}"), ensure_ascii=False, indent=2))
    return 0


def cmd_counties(_args: argparse.Namespace) -> int:
    print(json.dumps(api.rest_get("/reference-data/counties"), ensure_ascii=False, indent=2))
    return 0


def _walk(cats: list[dict[str, Any]], path: str = "") -> list[tuple[int, str]]:
    out = []
    for c in cats or []:
        name = f"{path} > {c.get('name')}" if path else str(c.get("name"))
        out.append((c.get("id"), name))
        out.extend(_walk(c.get("childCategories") or [], name))
    return out


def cmd_categories(args: argparse.Namespace) -> int:
    rows = _walk(api.rest_get("/categories"))
    needle = (args.grep or "").lower()
    for cid, name in rows:
        if needle in name.lower():
            print(f"{cid:>10}  {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradera", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="search active listings (auctions + buy now)")
    s.add_argument("query")
    s.add_argument("--min-price", type=int)
    s.add_argument("--max-price", type=int)
    s.add_argument("--category", type=int, help="category id (see `tradera categories`)")
    s.add_argument("--county", type=int, help="county id (see `tradera counties`)")
    s.add_argument("--zip", help="zip code")
    s.add_argument("--sort", choices=api.ORDER_BY, default="Relevance")
    s.add_argument("--type", choices=api.ITEM_TYPES, help="auction or fixed price")
    s.add_argument("--condition", choices=api.ITEM_CONDITIONS)
    s.add_argument("--seller", choices=api.SELLER_TYPES)
    s.add_argument("--in-description", action="store_true", help="match description too")
    s.add_argument("--ended", action="store_true", help="ended listings instead (price history)")
    s.add_argument("--per-page", type=int, default=50)
    s.add_argument("--pages", type=int, default=1, help="max pages to fetch (default 1)")
    s.add_argument("--limit", type=int, help="cap printed results")
    s.add_argument("--json", action="store_true", help="raw JSON output")
    s.set_defaults(func=cmd_search)

    i = sub.add_parser("item", help="full item data by id (REST v4)")
    i.add_argument("id", type=int)
    i.set_defaults(func=cmd_item)

    c = sub.add_parser("counties", help="list county ids")
    c.set_defaults(func=cmd_counties)

    g = sub.add_parser("categories", help="list category ids, optionally filtered")
    g.add_argument("grep", nargs="?", help="substring filter on the category path")
    g.set_defaults(func=cmd_categories)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
