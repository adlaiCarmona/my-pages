import os
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "cache")

OUTPUT_HTML = os.path.join(_HERE, "index.html")
PRICE_HISTORY_FILE = os.path.join(_HERE, "price_history.json")
PRICE_HISTORY_CACHE_FILE = os.path.join(CACHE_DIR, "price-history.json")

_sets_path = os.path.join(_HERE, "sets.json")
with open(_sets_path) as _f:
    SETS: set[str] = set(json.load(_f))

PRODUCT_LINE = "one-piece-card-game"

SEARCH_URL = "https://mp-search-api.tcgplayer.com/v1/search/request?q=&isList=false&mpfev=5111"
SEARCH_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}

PRICE_HISTORY_API = "https://infinite-api.tcgplayer.com/price/history/{pid}/detailed?range=annual"
PRICE_HISTORY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:150.0) Gecko/20100101 Firefox/150.0",
}

IMAGE_BASE = "https://tcgplayer-cdn.tcgplayer.com/product"
IMAGE_SIZE = "400x400"

# Maps set slug → display ID prefix (e.g. "OP01").
SET_IDS: dict[str, str] = {
    "romance-dawn":                                 "OP01",
    "paramount-war":                                "OP02",
    "pillars-of-strength":                          "OP03",
    "kingdoms-of-intrigue":                         "OP04",
    "awakening-of-the-new-era":                     "OP05",
    "wings-of-the-captain":                         "OP06",
    "500-years-in-the-future":                      "OP07",
    "two-legends":                                  "OP08",
    "emperors-in-the-new-world":                    "OP09",
    "royal-blood":                                  "OP10",
    "a-fist-of-divine-speed":                       "OP11",
    "legacy-of-the-master":                         "OP12",
    "carrying-on-his-will":                         "OP13",
    "the-azure-seas-seven":                         "OP14",
    "adventure-on-kamis-island":                    "OP15",
    "the-time-of-battle":                           "OP16",
    "extra-booster-anime-25th-collection":          "EB02",
    "extra-booster-one-piece-heroines-edition":     "EB03",
}

PRICE_BUCKETS: list[tuple[int, int | None, str]] = [
    (0,    10,  "$0–10"),
    (10,   50,  "$10–50"),
    (50,   100, "$50–100"),
    (100,  250, "$100–250"),
    (250,  500, "$250–500"),
    (500,  None, "$500+"),
]

RARITY_ORDER = ["C", "UC", "R", "SR", "SEC", "SP", "L", "PR", "TR", "DON!!"]

PRICE_HISTORY_MIN_PRICE = 75.0  # only fetch price history for cards above this price
