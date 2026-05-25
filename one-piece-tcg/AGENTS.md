# One Piece TCG Price Tracker — Agent Context

## What this project does

Fetches the top 50 most-expensive cards per set from the TCGPlayer marketplace API, tracks price and rank changes over time, and generates a static `index.html` dashboard. The page shows per-card price/rank deltas, a booster-box break-even calculator, a price distribution chart, and an annual price history chart rendered on a Canvas element inside a card detail overlay.

Run the script manually whenever a fresh snapshot is wanted:

```bash
python3 fetch_top_cards.py           # uses disk cache where available
python3 fetch_top_cards.py --no-cache  # bypasses all caches, re-fetches everything
```

---

## File map

| File | Purpose |
|---|---|
| `fetch_top_cards.py` | Entry point. Orchestrates fetching, comparison, sorting, HTML write, and price-history save. Keep this file thin. |
| `constants.py` | Every constant: API URLs, headers, `SET_IDS`, `PRICE_BUCKETS`, file paths, `PRICE_HISTORY_MIN_PRICE`. Edit set IDs here when new sets release. |
| `tcgplayer_api.py` | `fetch_top_cards()`, `get_price()`, `get_card_info()`, `card_image_url()`. Handles the TCGPlayer search API and disk cache per set. |
| `price_history_cache.py` | `PriceHistoryCache` class. Loads/saves `cache/price-history.json`. Marks the endpoint dead after the first failure so subsequent cards are skipped silently. |
| `price_tracker.py` | `load()` / `save()` for `price_history.json`. Stores per-card `{price, rank, name, scan_date}` and per-set totals under the reserved `_sets` key. |
| `html_builder.py` | All HTML generation. Card HTML, set sections, breakeven panel, price distribution chart, sidebar nav. Reads `template.html` and fills named `{placeholders}`. |
| `template.html` | Static HTML shell. Contains `{set_nav}`, `{set_sections}`, `{grand_total}`, `{last_scan_html}`, `{price_history_json}` placeholders filled by `html_builder.py`. |
| `app.js` | All client-side JavaScript: card overlay, Canvas price-history chart, rarity filters, hamburger sidebar, break-even calculator. No build step. |
| `style.css` | All CSS. Uses CSS custom properties (`--var`) for every colour. No inline styles in Python output except dynamically computed bar heights/colours. |
| `sets.json` | List of set slugs to fetch (kebab-case, e.g. `"romance-dawn"`). Add new sets here. |
| `price_history.json` | Persisted price/rank snapshot from the last scan. Updated only once per calendar day (UTC). |
| `cache/` | Disk cache directory. `{set-slug}.json` per set (search results). `price-history.json` for all card price histories (keyed by `str(int(product_id))`). |
| `index.html` | Generated output. Do not edit by hand — it is overwritten on every run. |

---

## Key data flows

### Per-set card data
1. `fetch_top_cards(set_name)` → POST to TCGPlayer search API → cached in `cache/{set-slug}.json`
2. Results parsed with `get_card_info()` / `get_price()`
3. Compared against `price_history.json` to compute `price_change` and `rank_change`

### Annual price history
1. Only fetched for cards with `price > PRICE_HISTORY_MIN_PRICE` (currently $50)
2. `PriceHistoryCache.get(product_id)` → GET `https://infinite-api.tcgplayer.com/price/history/{pid}/detailed?range=annual`
3. First result entry (Near Mint) stored as `{condition, buckets: [str×52]}` in `cache/price-history.json`
4. Buckets are **stored reversed** so index 0 = oldest week, index 51 = most recent week
5. If the endpoint returns an error for any card, `_endpoint_dead` is set and no further cards attempt a fetch

### HTML generation
1. `build_html(sets_data)` reads `template.html`, fills placeholders
2. Price history map serialised as `const PRICE_HISTORY = {...}` injected inline into the HTML (no client-side fetch, no CORS)
3. `app.js` reads `PRICE_HISTORY[productId]` when an overlay opens and draws the Canvas chart

---

## Critical implementation details

- **Product ID keying**: the TCGPlayer API returns `productId` as a float (e.g. `454666.0`). Always normalise with `str(int(product_id))` before using as a dict key. Inconsistency here causes all cards to appear as NEW.
- **`_sets` reserved key**: `price_history.json` stores per-set totals under `"_sets"`. Skip this key when iterating card entries.
- **Price history buckets**: values are strings (`"18.81"`). A value of `"0"` means the card did not exist that week — skip it in the chart.
- **Bucket order**: index 0 is the oldest week, index 51 is the most recent. If existing cache entries need to be flipped, run the one-off migration script pattern: `entry['buckets'] = list(reversed(entry['buckets']))` for each entry in `cache/price-history.json`.
- **Price history save guard**: `price_history.json` is only written when today's UTC date differs from the stored `scan_date`. This prevents double-counting intra-day re-runs.
- **`--no-cache` flag**: bypasses both the set search cache (`cache/{slug}.json`) and the price history cache (`cache/price-history.json`).
- **CORS**: all API calls happen in Python at build time. `app.js` never fetches anything — price history is embedded in the HTML as a JS variable.
- **`template.html` placeholders**: they use single-brace `{name}` Python `.format()` syntax. Do not use `{{` / `}}` escaping in the template itself — that is only needed inside Python f-strings.

---

## Adding a new set

1. Add the kebab-case slug to `sets.json`.
2. Add the slug → set ID mapping to `SET_IDS` in `constants.py`.
3. Run `python3 fetch_top_cards.py`.

---

## Styling conventions

- All colours are CSS custom properties defined on `:root` in `style.css`. Never hardcode hex values in Python or JS.
- Price tiers use classes: `price-high` (≥$50), `price-mid` (≥$10), `price-low` (<$10).
- Rank/price delta badges use: `rank-new`, `rank-up`, `rank-down`, `delta-up`, `delta-down`, `delta-flat`.

---

## Dependencies

```
requests   # pip install -r requirements.txt
```

No frontend build tools. `app.js` is plain ES2020, loaded via `<script src="app.js">`.
