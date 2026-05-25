"""Cache for annual price history data from TCGPlayer Infinite API.

All entries are stored in a single JSON file: cache/price-history.json
keyed by str(int(product_id)).
"""
import json
import os

import requests

from constants import (
    CACHE_DIR,
    PRICE_HISTORY_API,
    PRICE_HISTORY_CACHE_FILE,
    PRICE_HISTORY_HEADERS,
)


class PriceHistoryCache:
    def __init__(self) -> None:
        self._data: dict | None = None
        self._endpoint_dead = False

    def _load(self) -> dict:
        if self._data is None:
            if os.path.exists(PRICE_HISTORY_CACHE_FILE):
                with open(PRICE_HISTORY_CACHE_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            else:
                self._data = {}
        return self._data

    def _save(self) -> None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(PRICE_HISTORY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, product_id, force_fetch: bool = False) -> dict | None:
        """Return price history for *product_id*, fetching from the API if needed.

        Returns a dict ``{"condition": str, "buckets": [str, ...]}`` or ``None``.
        Once the endpoint fails for any card, all further calls return ``None``
        without hitting the network.
        """
        if self._endpoint_dead:
            return None

        pid = str(int(product_id))
        cache = self._load()

        if not force_fetch and pid in cache:
            return cache[pid]

        url = PRICE_HISTORY_API.format(pid=pid)
        try:
            resp = requests.get(url, headers=PRICE_HISTORY_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(
                f"    [price-history] fetch failed for {pid}: {e}"
                " — skipping price history for remaining cards"
            )
            self._endpoint_dead = True
            return None

        results = data.get("result", [])
        if not results:
            return None

        entry = results[0]  # first condition (usually Near Mint)
        payload = {
            "condition": entry.get("condition", ""),
            "buckets": [
                b.get("marketPrice", "0")
                for b in reversed(entry.get("buckets", []))
            ],
        }
        cache[pid] = payload
        self._save()
        return payload
