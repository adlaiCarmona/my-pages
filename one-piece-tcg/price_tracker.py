"""Load and save the price history snapshot (price_history.json)."""
import json
import os

from constants import PRICE_HISTORY_FILE


def load() -> dict:
    """Return previous price snapshot, or ``{}`` if none exists.

    Structure::

        {
            "<product_id>": {"price": float, "rank": int, "name": str, "scan_date": str},
            "_sets": {"<slug>": {"total": float, "scan_date": str}},
        }
    """
    if os.path.exists(PRICE_HISTORY_FILE):
        with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(sets_data: list[dict], scan_date: str) -> None:
    """Persist current prices, ranks, and set totals for next-run comparison."""
    history: dict = {}

    for s in sets_data:
        for card in s["cards"]:
            pid = str(int(card["product_id"])) if card["product_id"] else ""
            if pid:
                history[pid] = {
                    "price":     card["price"],
                    "rank":      card["rank"],
                    "name":      card["name"],
                    "scan_date": scan_date,
                }

    history["_sets"] = {
        s["slug"]: {"total": s["total"], "scan_date": scan_date}
        for s in sets_data
    }

    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
    print(f"  Price history saved to: {PRICE_HISTORY_FILE}")
