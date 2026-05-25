"""One Piece TCG price tracker — entry point.

Usage:
    python fetch_top_cards.py [--no-cache]
"""
import argparse
from datetime import datetime, timezone

import requests

import price_tracker
from constants import OUTPUT_HTML, PRICE_HISTORY_MIN_PRICE, SET_IDS, SETS
from html_builder import build_html
from price_history_cache import PriceHistoryCache
from tcgplayer_api import card_image_url, fetch_top_cards, get_card_info, get_price


def _set_sort_key(s: dict):
    sid = SET_IDS.get(s["slug"], "").upper()
    if sid.startswith("OP"):
        return (0, sid)
    if sid.startswith("EB"):
        return (1, sid)
    if sid:
        return (2, sid)
    return (3, s["slug"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch top One Piece TCG cards and build index.html"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Ignore cached data and fetch fresh results from the API",
    )
    args = parser.parse_args()
    force_fetch = args.no_cache

    if not SETS:
        print("No sets defined. Add set name slugs to sets.json.")
        return

    # Load previous price snapshot
    prev_history = price_tracker.load()
    last_scan_date: str | None = None
    if prev_history:
        dates = [v["scan_date"] for v in prev_history.values() if "scan_date" in v]
        if dates:
            last_scan_date = max(dates)
        print(f"Loaded price history ({len(prev_history)} entries). Last scan: {last_scan_date}")
    else:
        print("No previous price history — this will be the first baseline.")

    ph_cache = PriceHistoryCache()
    sets_data: list[dict] = []

    for set_name in SETS:
        print(f"\n{'=' * 60}")
        print(f"Set: {set_name}")
        print(f"{'=' * 60}")

        try:
            cards = fetch_top_cards(set_name, force_fetch=force_fetch)
        except requests.HTTPError as e:
            print(f"  HTTP error fetching '{set_name}': {e}")
            continue
        except Exception as e:
            print(f"  Error fetching '{set_name}': {e}")
            continue

        if not cards:
            print("  No cards found.")
            continue

        total = 0.0
        card_rows: list[dict] = []

        for i, result in enumerate(cards, start=1):
            try:
                price = get_price(result)
            except Exception:
                price = 0.0

            info = get_card_info(result)
            name = result.get("productName", result.get("name", "Unknown"))

            print(
                f"  {i:>2}. [{info['number'] or '':>10}] "
                f"{name:<50}  "
                f"{info['rarityDbName'] or '':>5} / {info['rarityName'] or '':<20}  "
                f"ID:{int(info['productId']) if info['productId'] else 'N/A':<10}  "
                f"${price:>8.2f}"
            )

            total += price

            pid_str = str(int(info["productId"])) if info["productId"] else ""
            prev = prev_history.get(pid_str)
            if prev is not None:
                price_change = round(price - prev["price"], 2)
                prev_rank    = prev.get("rank")
                rank_change  = (prev_rank - i) if prev_rank is not None else None
            else:
                price_change = None
                rank_change  = None

            ph_data = (
                ph_cache.get(info["productId"], force_fetch=force_fetch)
                if info["productId"] and price > PRICE_HISTORY_MIN_PRICE
                else None
            )

            card_rows.append({
                "name":          name,
                "price":         price,
                "price_change":  price_change,
                "rank":          i,
                "rank_change":   rank_change,
                "product_id":    info["productId"],
                "number":        info["number"],
                "rarity_db":     info["rarityDbName"],
                "rarity_name":   info["rarityName"],
                "image_url":     card_image_url(info["productId"]),
                "card_type":     info["cardType"],
                "life":          info["life"],
                "counter":       info["counter"],
                "power":         info["power"],
                "cost":          info["cost"],
                "subtypes":      info["subtypes"],
                "attribute":     info["attribute"],
                "color":         info["color"],
                "description":   info["description"],
                "price_history": ph_data,
            })

        avg = total / len(card_rows) if card_rows else 0.0
        print(f"\n  Top {len(card_rows)} cards total value:  ${total:.2f}")
        print(f"  Average price:              ${avg:.2f}")

        prev_sets      = prev_history.get("_sets", {})
        prev_set_total = prev_sets.get(set_name, {}).get("total")
        total_change   = round(total - prev_set_total, 2) if prev_set_total is not None else None

        # Build display name from slug + set ID prefix
        base_name    = result.get("setName", set_name.replace("-", " ").title())
        set_id       = SET_IDS.get(set_name, "")
        display_name = f"{set_id} – {base_name}" if set_id else base_name

        sets_data.append({
            "slug":         set_name,
            "name":         display_name,
            "cards":        card_rows,
            "total":        total,
            "total_change": total_change,
            "avg":          avg,
        })

    if not sets_data:
        return

    sets_data.sort(key=_set_sort_key)

    html = build_html(sets_data, last_scan_date=last_scan_date)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHTML report saved to: {OUTPUT_HTML}")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    today   = datetime.now(timezone.utc).date()

    if last_scan_date is None:
        last_scan_day = None
    else:
        try:
            last_scan_day = datetime.strptime(last_scan_date[:10], "%Y-%m-%d").date()
        except ValueError:
            last_scan_day = None

    if last_scan_day != today:
        price_tracker.save(sets_data, now_str)
        print(f"Price history updated at: {now_str}")
    else:
        print(f"Price history unchanged (already scanned today: {today})")


if __name__ == "__main__":
    main()
