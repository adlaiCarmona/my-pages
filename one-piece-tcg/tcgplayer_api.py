"""TCGPlayer API helpers: fetching card data for a set."""
import json
import os

import requests

from constants import (
    CACHE_DIR,
    IMAGE_BASE,
    IMAGE_SIZE,
    PRODUCT_LINE,
    SEARCH_HEADERS,
    SEARCH_URL,
)


# ---------------------------------------------------------------------------
# Search / card data
# ---------------------------------------------------------------------------

def build_payload(set_name: str) -> dict:
    return {
        "algorithm": "sales_exp_fields_experiment",
        "from": 0,
        "size": 50,
        "filters": {
            "term": {
                "productLineName": [PRODUCT_LINE],
                "setName": [set_name],
                "productTypeName": ["Cards"],
            },
            "range": {},
            "match": {},
        },
        "listingSearch": {
            "context": {"cart": {"packages": {}}},
            "filters": {
                "term": {"sellerStatus": "Live", "channelId": 0},
                "range": {"quantity": {"gte": 1}},
                "exclude": {"channelExclusion": 0},
            },
        },
        "context": {
            "cart": {"packages": {}},
            "shippingCountry": "US",
            "userProfile": {},
        },
        "settings": {"useFuzzySearch": True, "didYouMean": {}},
        "sort": {"field": "market-price", "order": "desc"},
    }


def cache_path(set_name: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{set_name}.json")


def fetch_top_cards(set_name: str, force_fetch: bool = False) -> list[dict]:
    """Return raw card result dicts for *set_name*, using disk cache when available."""
    path = cache_path(set_name)

    if not force_fetch and os.path.exists(path):
        print(f"  (loaded from cache: {path})")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        if force_fetch:
            print("  (force fetch — skipping cache)")
        payload = build_payload(set_name)
        response = requests.post(SEARCH_URL, headers=SEARCH_HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"  (response saved to cache: {path})")

    api_results = data.get("results", [])[0] if data.get("results") else {}
    return api_results.get("results", [])


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def get_price(result: dict) -> float:
    price = result.get("marketPrice")
    return float(price) if price is not None else 0.0


def get_card_info(result: dict) -> dict:
    custom = result.get("customAttributes", {})

    def join_list(val):
        if isinstance(val, list):
            return ", ".join(str(v) for v in val if v)
        return val or ""

    return {
        "productId":    result.get("productId"),
        "rarityName":   result.get("rarityName"),
        "number":       custom.get("number"),
        "rarityDbName": custom.get("rarityDbName"),
        "cardType":     join_list(custom.get("cardType")),
        "life":         custom.get("life") or "",
        "counter":      custom.get("counter") or "",
        "power":        custom.get("power") or "",
        "cost":         custom.get("cost") or "",
        "subtypes":     join_list(custom.get("subtypes")),
        "attribute":    join_list(custom.get("attribute")),
        "color":        join_list(custom.get("color")),
        "description":  custom.get("description") or "",
    }


def card_image_url(product_id, size: str = IMAGE_SIZE) -> str:
    pid = int(product_id) if product_id else 0
    return f"{IMAGE_BASE}/{pid}_in_{size}.jpg"
