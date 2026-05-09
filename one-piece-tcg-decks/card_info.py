"""
Utility to fetch card metadata from the OPTCG API.

Usage:
    from card_info import get_card_info

    info = get_card_info("OP01-033")
    # Returns a dict with: market_price, rarity, card_text, card_color,
    # card_type, card_cost, card_power, sub_types, counter_amount, attribute
    # or None if the card is not found / request fails.
"""

import time
import requests

_API_BASE_SETS  = "https://www.optcgapi.com/api/sets/card"
_API_BASE_DECKS = "https://www.optcgapi.com/api/decks/card"
_CACHE: dict[str, dict | None] = {}
_REQUEST_DELAY = 0.3  # seconds — be polite to the free API

FIELDS = (
    "market_price",
    "rarity",
    "card_text",
    "card_color",
    "card_type",
    "card_cost",
    "card_power",
    "sub_types",
    "counter_amount",
    "attribute",
)


def get_card_info(card_id: str) -> dict | None:
    """
    Return a dict of card metadata for *card_id* (e.g. "OP01-033").

    The API may return multiple printings for the same ID (base + parallels).
    We always use the first entry (base print) for static fields and take
    the lowest non-None market_price across all printings so the displayed
    price is the cheapest available version.

    Returns None if the card cannot be found or the request fails.
    Results are cached in-process so each card ID is only fetched once.
    """
    card_id = card_id.upper()
    if card_id in _CACHE:
        return _CACHE[card_id]

    api_base = _API_BASE_DECKS if card_id.startswith("ST") else _API_BASE_SETS
    url = f"{api_base}/{card_id}"
    try:
        resp = requests.get(url, timeout=15)
        time.sleep(_REQUEST_DELAY)

        if resp.status_code == 404:
            _CACHE[card_id] = None
            return None

        resp.raise_for_status()
        data = resp.json()

        if not data:
            _CACHE[card_id] = None
            return None

        # Base print is the first entry
        base = data[0]

        # Cheapest market price across all printings
        prices = [
            entry["market_price"]
            for entry in data
            if entry.get("market_price") is not None
        ]
        cheapest_price = min(prices) if prices else None

        info = {field: base.get(field) for field in FIELDS}
        info["market_price"] = cheapest_price

        _CACHE[card_id] = info
        return info

    except Exception as exc:
        print(f"  [card_info] Failed to fetch {card_id}: {exc}")
        _CACHE[card_id] = None
        return None
