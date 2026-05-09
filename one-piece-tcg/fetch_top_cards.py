import requests
import json
import os

# Set slugs are loaded from sets.json (kebab-case, e.g. "adventure-on-kamis-island")
_sets_path = os.path.join(os.path.dirname(__file__), "sets.json")
with open(_sets_path) as _f:
    SETS = set(json.load(_f))

PRODUCT_LINE = "one-piece-card-game"

URL = "https://mp-search-api.tcgplayer.com/v1/search/request?q=&isList=false&mpfev=5111"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "cache")


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


def fetch_top_cards(set_name: str) -> list[dict]:
    path = cache_path(set_name)

    if os.path.exists(path):
        print(f"  (loaded from cache: {path})")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        payload = build_payload(set_name)
        response = requests.post(URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"  (response saved to cache: {path})")

    apiResults = data.get("results", [])[0] if data.get("results") else {}
    cardsResults = apiResults.get("results", [])
    
    return cardsResults


def get_price(result: dict) -> float:
    # Update this path once you know the exact price field
    price = result.get("marketPrice")  # noqa: placeholder — update as needed
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


IMAGE_BASE = "https://tcgplayer-cdn.tcgplayer.com/product"
IMAGE_SIZE = "400x400"
OUTPUT_HTML = os.path.join(_HERE, "index.html")


def card_image_url(product_id, size=IMAGE_SIZE) -> str:
    pid = int(product_id) if product_id else 0
    return f"{IMAGE_BASE}/{pid}_in_{size}.jpg"


PRICE_BUCKETS = [
    (0,   10,  "$0–10"),
    (10,  50,  "$10–50"),
    (50,  100, "$50–100"),
    (100, 250, "$100–250"),
    (250, 500, "$250–500"),
    (500, None, "$500+"),
]


def price_buckets(cards: list[dict]) -> list[tuple[str, int]]:
    results = []
    for lo, hi, label in PRICE_BUCKETS:
        count = sum(
            1 for c in cards
            if c["price"] >= lo and (hi is None or c["price"] < hi)
        )
        results.append((label, count))
    return results


def build_html(sets_data: list[dict]) -> str:
    set_nav = "\n".join(
        f'<li><a href="#{s["slug"]}">{s["name"]}</a>'
        f'<span class="nav-total">${s["total"]:.2f}</span></li>'
        for s in sets_data
    )

    set_sections = ""
    for s in sets_data:
        cards_html = ""
        for i, card in enumerate(s["cards"], start=1):
            price_cls = "price-high" if card["price"] >= 50 else ("price-mid" if card["price"] >= 10 else "price-low")
            import html as _html
            desc_escaped = _html.escape(card['description'], quote=True)
            cards_html += f"""
        <div class="card" role="button" tabindex="0"
          data-name="{_html.escape(card['name'], quote=True)}"
          data-price="${card['price']:.2f}"
          data-image="{card['image_url']}"
          data-number="{card['number'] or ''}"
          data-rarity-db="{card['rarity_db'] or ''}"
          data-rarity-name="{_html.escape(card['rarity_name'] or '', quote=True)}"
          data-card-type="{_html.escape(card['card_type'], quote=True)}"
          data-life="{card['life']}"
          data-counter="{card['counter']}"
          data-power="{card['power']}"
          data-cost="{card['cost']}"
          data-subtypes="{_html.escape(card['subtypes'], quote=True)}"
          data-attribute="{_html.escape(card['attribute'], quote=True)}"
          data-color="{_html.escape(card['color'], quote=True)}"
          data-description="{desc_escaped}"
          data-product-id="{int(card['product_id']) if card['product_id'] else ''}"
        >
          <div class="card-rank">#{i}</div>
          <img
            class="card-img"
            src="{card['image_url']}"
            alt="{card['name']}"
            loading="lazy"
          />
          <div class="card-body">
            <div class="card-name">{card['name']}</div>
            <div class="card-meta">
              <span class="badge">{card['number'] or '—'}</span>
              <span class="badge rarity">{card['rarity_db'] or '—'}</span>
              <span class="rarity-name">{card['rarity_name'] or '—'}</span>
            </div>
            <div class="card-id">ID: {int(card['product_id']) if card['product_id'] else 'N/A'}</div>
            <div class="card-price {price_cls}">${card['price']:.2f}</div>
          </div>
        </div>"""

        # ── Breakeven data ──────────────────────────────────────────
        # A card is a "hit" if its name contains (SP), (Manga), or (Alternate Art),
        # OR if it is a plain SEC card (no variant suffix).
        import re
        HIT_SUFFIXES = re.compile(r'\((SP|Manga|Alternate Art)\)', re.IGNORECASE)

        def is_hit(c):
            return bool(HIT_SUFFIXES.search(c["name"])) or (
                c["rarity_db"] == "SEC" and not re.search(r'\(', c["name"].split(c["name"].split("(")[0])[-1] if "(" in c["name"] else "")
            )

        # Simpler: hit if name has a known hit suffix, or rarity is SEC
        def is_hit(c):
            name = c["name"]
            return bool(HIT_SUFFIXES.search(name)) or c["rarity_db"] == "SEC"

        hits        = [c for c in s["cards"] if is_hit(c)]
        manga_hits  = [c for c in hits if re.search(r'\(Manga\)', c["name"], re.IGNORECASE)]
        alt_hits    = [c for c in hits if re.search(r'\(Alternate Art\)', c["name"], re.IGNORECASE)]
        sp_hits     = [c for c in hits if re.search(r'\(SP\)', c["name"], re.IGNORECASE)]
        sec_hits    = [c for c in hits if c["rarity_db"] == "SEC" and not re.search(r'\((SP|Manga|Alternate Art)\)', c["name"], re.IGNORECASE)]

        # Normal hits = SP + plain SEC (pull odds similar); Alt Art and Manga are rarer
        normal_hits = sp_hits + sec_hits + alt_hits
        avg_normal_hit = (sum(c["price"] for c in normal_hits) / len(normal_hits)) if normal_hits else 0.0
        avg_manga_hit  = (sum(c["price"] for c in manga_hits)  / len(manga_hits))  if manga_hits  else 0.0

        # Expected value per box:
        #   2 normal hits + 0.2 manga hits (1 per 5 boxes)
        ev_per_box = 2 * avg_normal_hit + 0.2 * avg_manga_hit

        def hit_type(c):
            if re.search(r'\(Manga\)', c["name"], re.IGNORECASE):        return "Manga"
            if re.search(r'\(Alternate Art\)', c["name"], re.IGNORECASE): return "Alt Art"
            if re.search(r'\(SP\)', c["name"], re.IGNORECASE):            return "SP"
            return "SEC"

        hit_cards_json = json.dumps([
            {"name": c["name"], "price": c["price"], "rarity": c["rarity_db"], "type": hit_type(c)}
            for c in hits
        ])

        buckets = price_buckets(s["cards"])
        max_count = max((c for _, c in buckets), default=1) or 1
        bucket_colors = ["#34d399", "#a3e635", "#fbbf24", "#fb923c", "#f87171", "#c084fc"]
        chart_bars = ""
        summary_pills = ""
        for idx, (label, count) in enumerate(buckets):
            pct = round(count / max_count * 100)
            color = bucket_colors[idx % len(bucket_colors)]
            empty_cls = "" if count else " bucket-empty"
            chart_bars += f"""
              <div class="bar-group">
                <div class="bar-wrap">
                  <span class="bar-val">{count}</span>
                  <div class="bar" style="height:{pct}%;background:{color};"></div>
                </div>
                <div class="bar-label">{label}</div>
              </div>"""
            summary_pills += (
                f'<div class="bucket{empty_cls}">'
                f'<span class="bucket-label">{label}</span>'
                f'<span class="bucket-count" style="color:{color if count else "#44445a"}">{count}</span>'
                f'</div>'
            )

        set_sections += f"""
  <section class="set-section" id="{s['slug']}">
    <div class="set-header">
      <h2>{s['name']}</h2>
      <div class="set-stats">
        <span>Top {len(s['cards'])} cards</span>
        <span class="set-total">Total: ${s['total']:.2f}</span>
        <span class="set-avg">Avg: ${s['avg']:.2f}</span>
      </div>
    </div>
    <div class="price-buckets">{summary_pills}</div>
    <details class="chart-details">
      <summary class="chart-toggle">Price distribution chart</summary>
      <div class="chart">
        <div class="chart-bars">{chart_bars}
        </div>
      </div>
    </details>
    <details class="chart-details breakeven-details" data-ev="{ev_per_box:.4f}">
      <summary class="chart-toggle">Booster box break-even calculator</summary>
      <div class="breakeven-panel">
        <div class="box-price-row">
          <label for="box-price-{s['slug']}">Booster box price:</label>
          <input id="box-price-{s['slug']}" class="box-price-input" type="number" min="0" step="0.01" value="350" />
        </div>
        <div class="be-grid">
          <div class="be-stat">
            <span class="be-label">SP hits ({len(sp_hits)})</span>
            <span class="be-value">{f'${sum(c["price"] for c in sp_hits)/len(sp_hits):.2f} avg' if sp_hits else '—'}</span>
          </div>
          <div class="be-stat">
            <span class="be-label">Alternate Art hits ({len(alt_hits)})</span>
            <span class="be-value">{f'${sum(c["price"] for c in alt_hits)/len(alt_hits):.2f} avg' if alt_hits else '—'}</span>
          </div>
          <div class="be-stat">
            <span class="be-label">SEC hits ({len(sec_hits)})</span>
            <span class="be-value">{f'${sum(c["price"] for c in sec_hits)/len(sec_hits):.2f} avg' if sec_hits else '—'}</span>
          </div>
          <div class="be-stat">
            <span class="be-label">Manga hits ({len(manga_hits)}, 1-in-5 boxes)</span>
            <span class="be-value">{f'${avg_manga_hit:.2f} avg' if manga_hits else '—'}</span>
          </div>
          <div class="be-stat">
            <span class="be-label">Avg normal hit value</span>
            <span class="be-value">${avg_normal_hit:.2f}</span>
          </div>
          <div class="be-stat">
            <span class="be-label">Expected value / box</span>
            <span class="be-value be-ev">${ev_per_box:.2f}</span>
          </div>
        </div>
        <div class="be-result-row">
          <div class="be-result-box">
            <span class="be-result-label">Expected value</span>
            <span class="be-result-value be-ev-display" id="be-ev-{s['slug']}">${ev_per_box:.2f}</span>
          </div>
          <div class="be-result-box be-outcome-box" id="be-outcome-{s['slug']}">
            <span class="be-result-label">Outcome</span>
            <span class="be-result-value" id="be-outcome-val-{s['slug']}">—</span>
          </div>
          <div class="be-result-box">
            <span class="be-result-label">Boxes to break even</span>
            <span class="be-result-value" id="be-boxes-{s['slug']}">—</span>
          </div>
        </div>
      </div>
    </details>
    <div class="cards-grid">
      {cards_html}
    </div>
  </section>"""

    grand_total = sum(s["total"] for s in sets_data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TCG Top Cards</title>
  <link rel="shortcut icon" type="image/x-icon" href="../favicon.ico">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: system-ui, sans-serif;
      background: #0f0f13;
      color: #e0e0e0;
      min-height: 100vh;
    }}

    /* ── Sidebar nav ── */
     .sidebar {{
       position: fixed;
       top: 0; left: 0;
       width: 240px;
       height: 100vh;
       background: #17171f;
       border-right: 1px solid #2a2a3a;
       overflow-y: auto;
       padding: 1.5rem 0;
       z-index: 100;
       display: flex;
       flex-direction: column;
     }}
     .sidebar-logo {{
       display: block;
       width: 140px;
       margin: 0 auto 1rem;
     }}
     .sidebar h1 {{
       font-size: 1rem;
       font-weight: 700;
       color: #a78bfa;
       padding: 0 1.2rem 1rem;
       border-bottom: 1px solid #2a2a3a;
       margin-bottom: .8rem;
     }}
    .sidebar ul {{ list-style: none; }}
    .sidebar li {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: .1rem .4rem .1rem 1.2rem;
    }}
    .sidebar a {{
      color: #c4c4d4;
      text-decoration: none;
      font-size: .85rem;
      flex: 1;
      padding: .35rem 0;
    }}
    .sidebar a:hover {{ color: #a78bfa; }}
    .nav-total {{
      font-size: .75rem;
      color: #6b6b8a;
      white-space: nowrap;
    }}
    .grand-total {{
      margin: 1rem 1.2rem 0;
      padding-top: .8rem;
      border-top: 1px solid #2a2a3a;
      font-size: .8rem;
      color: #a78bfa;
    }}

    /* ── Main content ── */
    .main {{
      margin-left: 240px;
      padding: 2rem 2rem 4rem;
    }}

    /* ── Set section ── */
    .set-section {{
      margin-bottom: 3.5rem;
      scroll-margin-top: 1.5rem;
    }}
    .set-header {{
      position: sticky;
      top: 0;
      z-index: 40;
      background: #0f0f13;
      display: flex;
      align-items: baseline;
      gap: 1.5rem;
      flex-wrap: wrap;
      margin-bottom: 1.2rem;
      padding: .6rem 0;
      border-bottom: 2px solid #2a2a3a;
    }}
    .set-header h2 {{
      font-size: 1.3rem;
      color: #a78bfa;
    }}
    .set-stats {{
      display: flex;
      gap: 1rem;
      font-size: .82rem;
      color: #6b6b8a;
    }}
    .set-total, .set-avg {{ color: #c4c4d4; }}

    /* ── Price buckets ── */
    .price-buckets {{
      display: flex;
      flex-wrap: wrap;
      gap: .5rem;
      margin-bottom: .8rem;
    }}
    .bucket {{
      display: flex;
      flex-direction: column;
      align-items: center;
      background: #1c1c28;
      border: 1px solid #2a2a3a;
      border-radius: 8px;
      padding: .4rem .8rem;
      min-width: 72px;
    }}
    .bucket-empty {{ opacity: .35; }}
    .bucket-label {{
      font-size: .65rem;
      color: #6b6b8a;
      white-space: nowrap;
    }}
    .bucket-count {{
      font-size: 1.15rem;
      font-weight: 700;
      line-height: 1.3;
    }}

    /* ── Collapsible chart ── */
    .chart-details {{
      margin-bottom: 1.2rem;
      border: 1px solid #2a2a3a;
      border-radius: 8px;
      overflow: hidden;
    }}
    .chart-toggle {{
      display: flex;
      align-items: center;
      gap: .5rem;
      padding: .55rem 1rem;
      background: #1c1c28;
      cursor: pointer;
      font-size: .8rem;
      color: #a78bfa;
      user-select: none;
      list-style: none;
    }}
    .chart-toggle::-webkit-details-marker {{ display: none; }}
    .chart-toggle::before {{
      content: "▶";
      font-size: .6rem;
      transition: transform .2s;
    }}
    .chart-details[open] .chart-toggle::before {{ transform: rotate(90deg); }}
    .chart-toggle:hover {{ background: #22222e; }}

    .chart {{
      padding: 1.2rem 1rem 1rem;
      background: #17171f;
    }}
    .chart-bars {{
      display: flex;
      align-items: flex-end;
      gap: .75rem;
      height: 140px;
    }}
    .bar-group {{
      display: flex;
      flex-direction: column;
      align-items: center;
      flex: 1;
      height: 100%;
    }}
    .bar-wrap {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-end;
      flex: 1;
      width: 100%;
      gap: 4px;
    }}
    .bar {{
      width: 100%;
      border-radius: 4px 4px 0 0;
      min-height: 3px;
      transition: opacity .15s;
    }}
    .bar:hover {{ opacity: .75; }}
    .bar-val {{
      font-size: .7rem;
      font-weight: 700;
      color: #c4c4d4;
    }}
    .bar-label {{
      font-size: .62rem;
      color: #6b6b8a;
      margin-top: .35rem;
      text-align: center;
      white-space: nowrap;
    }}

    /* ── Cards grid ── */
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 1rem;
    }}

    .card {{
      background: #1c1c28;
      border: 1px solid #2a2a3a;
      border-radius: 10px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: transform .15s, border-color .15s;
      position: relative;
      cursor: pointer;
    }}
    .card:hover {{
      transform: translateY(-3px);
      border-color: #a78bfa;
    }}

    .card-rank {{
      position: absolute;
      top: 6px; left: 6px;
      background: rgba(0,0,0,.65);
      color: #a78bfa;
      font-size: .7rem;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
    }}

    .card-img {{
      width: 100%;
      aspect-ratio: 1 / 1;
      object-fit: contain;
      background: #111118;
      display: block;
    }}

    .card-body {{
      padding: .6rem .7rem .75rem;
      display: flex;
      flex-direction: column;
      gap: .35rem;
    }}

    .card-name {{
      font-size: .78rem;
      font-weight: 600;
      color: #e0e0e0;
      line-height: 1.3;
    }}

    .card-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: .3rem;
      align-items: center;
    }}

    .badge {{
      background: #2a2a3a;
      color: #a0a0c0;
      font-size: .65rem;
      padding: 1px 5px;
      border-radius: 4px;
    }}
    .rarity {{ background: #2e1f4a; color: #c084fc; }}
    .rarity-name {{ font-size: .65rem; color: #6b6b8a; }}

    .card-id {{ font-size: .62rem; color: #44445a; }}

    .card-price {{
      font-size: 1rem;
      font-weight: 700;
      margin-top: .1rem;
    }}
    .price-high {{ color: #f87171; }}
    .price-mid  {{ color: #fbbf24; }}
    .price-low  {{ color: #34d399; }}

    /* ── Site header (mobile only) ── */
    .site-header {{
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0;
      height: 52px;
      background: #17171f;
      border-bottom: 1px solid #2a2a3a;
      z-index: 200;
      align-items: center;
      padding: 0 1rem;
      gap: .75rem;
    }}
    .site-header-logo {{
      height: 28px;
      flex: 1;
      object-fit: contain;
      object-position: left center;
    }}

    /* ── Hamburger button ── */
    .hamburger {{
      background: none;
      border: 1px solid #2a2a3a;
      border-radius: 7px;
      padding: .4rem .5rem;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 5px;
      align-items: center;
      justify-content: center;
    }}
    .hamburger span {{
      display: block;
      width: 20px;
      height: 2px;
      background: #a78bfa;
      border-radius: 2px;
    }}

    /* ── Sidebar backdrop (mobile) ── */
    .sidebar-backdrop {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.5);
      z-index: 99;
      opacity: 0;
      pointer-events: none;
      transition: opacity .25s;
    }}

    @media (max-width: 800px) {{
      .site-header {{ display: flex; }}
      .sidebar {{
        transform: translateX(-100%);
        transition: transform .25s ease;
        top: 52px;
        height: calc(100vh - 52px);
      }}
      .sidebar-logo {{ display: none; }}
      .sidebar.open {{ transform: translateX(0); }}
      .main {{ margin-left: 0; padding: 4rem 1rem 1rem; }}
      .sidebar-backdrop {{ display: block; }}
      .sidebar-backdrop.open {{ opacity: 1; pointer-events: all; }}
      .set-section {{ scroll-margin-top: 52px; }}
      .set-header {{ top: 52px; }}
    }}

    /* ── Card overlay ── */
    .overlay-backdrop {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.75);
      z-index: 200;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }}
    .overlay-backdrop.open {{ display: flex; }}
    .overlay {{
      background: #17171f;
      border: 1px solid #2a2a3a;
      border-radius: 14px;
      max-width: 780px;
      width: 100%;
      max-height: 90vh;
      overflow-y: auto;
      display: flex;
      gap: 1.5rem;
      padding: 1.5rem;
      position: relative;
    }}
    .overlay-img-col {{
      flex: 0 0 300px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 1rem;
    }}
    .overlay-img {{
      width: 300px;
      border-radius: 10px;
      display: block;
    }}
    .overlay-price {{
      font-size: 1.4rem;
      font-weight: 700;
    }}
    .overlay-info-col {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: .8rem;
      min-width: 0;
    }}
    .overlay-name {{
      font-size: 1.1rem;
      font-weight: 700;
      color: #fff;
      line-height: 1.3;
    }}
    .overlay-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: .35rem;
    }}
    .overlay-stats {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
      gap: .5rem;
    }}
    .overlay-stat {{
      background: #1c1c28;
      border: 1px solid #2a2a3a;
      border-radius: 7px;
      padding: .4rem .7rem;
      display: flex;
      flex-direction: column;
      gap: .1rem;
    }}
    .overlay-stat-label {{
      font-size: .6rem;
      color: #6b6b8a;
      text-transform: uppercase;
      letter-spacing: .05em;
    }}
    .overlay-stat-value {{
      font-size: .9rem;
      font-weight: 600;
      color: #e0e0e0;
    }}
    .overlay-desc {{
      font-size: .8rem;
      color: #b0b0c8;
      line-height: 1.6;
      border-top: 1px solid #2a2a3a;
      padding-top: .7rem;
    }}
    .overlay-close {{
      position: absolute;
      top: .8rem;
      right: .9rem;
      background: none;
      border: none;
      color: #6b6b8a;
      font-size: 1.3rem;
      cursor: pointer;
      line-height: 1;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    .overlay-close:hover {{ color: #e0e0e0; background: #2a2a3a; }}
    @media (max-width: 560px) {{
      .overlay {{ flex-direction: column; }}
      .overlay-img-col {{ flex: none; align-self: center; }}
    }}

    /* ── Breakeven panel ── */
    .breakeven-details {{ margin-top: .5rem; }}
    .box-price-row {{
      display: flex;
      align-items: center;
      gap: .75rem;
      font-size: .85rem;
      color: #c4c4d4;
      padding-bottom: .6rem;
      border-bottom: 1px solid #2a2a3a;
    }}
    .box-price-row label {{ color: #a78bfa; font-weight: 600; }}
    .box-price-input {{
      background: #0f0f13;
      border: 1px solid #3a3a5a;
      border-radius: 6px;
      color: #e0e0e0;
      font-size: .9rem;
      padding: .3rem .6rem;
      width: 100px;
      outline: none;
    }}
    .box-price-input:focus {{ border-color: #a78bfa; }}
    .breakeven-details {{ margin-top: .5rem; }}
    .breakeven-panel {{
      padding: 1.2rem;
      background: #17171f;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }}
    .be-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: .6rem;
    }}
    .be-stat {{
      background: #1c1c28;
      border: 1px solid #2a2a3a;
      border-radius: 8px;
      padding: .5rem .8rem;
      display: flex;
      flex-direction: column;
      gap: .15rem;
    }}
    .be-label {{ font-size: .65rem; color: #6b6b8a; }}
    .be-value {{ font-size: .95rem; font-weight: 700; color: #c4c4d4; }}
    .be-ev    {{ color: #a78bfa; }}

    .be-result-row {{
      display: flex;
      flex-wrap: wrap;
      gap: .6rem;
    }}
    .be-result-box {{
      flex: 1;
      min-width: 120px;
      background: #1c1c28;
      border: 1px solid #2a2a3a;
      border-radius: 8px;
      padding: .6rem 1rem;
      display: flex;
      flex-direction: column;
      gap: .2rem;
      text-align: center;
    }}
    .be-result-label {{ font-size: .65rem; color: #6b6b8a; }}
    .be-result-value {{ font-size: 1.1rem; font-weight: 700; color: #e0e0e0; }}
    .be-ev-display   {{ color: #a78bfa; }}
    .be-profit  {{ border-color: #34d399 !important; }}
    .be-profit .be-result-value {{ color: #34d399; }}
    .be-loss    {{ border-color: #f87171 !important; }}
    .be-loss .be-result-value   {{ color: #f87171; }}

    .be-hit-title {{ font-size: .7rem; color: #6b6b8a; margin-bottom: .4rem; }}
    .be-hit-cards {{ display: flex; flex-wrap: wrap; gap: .35rem; }}
    .be-hit-chip {{
      display: inline-flex;
      align-items: center;
      gap: .3rem;
      border-radius: 5px;
      font-size: .68rem;
      padding: 2px 7px;
      color: #c4c4d4;
      background: #2a2a3a;
    }}
    .be-hit-type {{
      font-style: normal;
      font-size: .58rem;
      font-weight: 700;
      padding: 1px 4px;
      border-radius: 3px;
      background: #3a3a50;
      color: #888;
    }}
    .be-hit-price {{ color: #a78bfa; font-style: normal; }}
    .be-type-sp            {{ background: #1e2a3a; }}
    .be-type-sp            .be-hit-type {{ background: #1e3a5a; color: #60a5fa; }}
    .be-type-sec           {{ background: #2a1e3a; }}
    .be-type-sec           .be-hit-type {{ background: #3a1e5a; color: #c084fc; }}
    .be-type-alt-art       {{ background: #1e2e2a; }}
    .be-type-alt-art       .be-hit-type {{ background: #1a3a30; color: #34d399; }}
    .be-type-manga         {{ background: #2e1f4a; border: 1px solid #7c3aed; }}
    .be-type-manga         .be-hit-type {{ background: #4a1e7a; color: #e879f9; }}
  </style>
</head>
<body>
  <header class="site-header">
    <img class="site-header-logo" src="../common/one-piece-full-logo.webp" alt="One Piece TCG" />
    <button class="hamburger" id="hamburger" aria-label="Open menu">
      <span></span><span></span><span></span>
    </button>
  </header>
  <div class="sidebar-backdrop" id="sidebar-backdrop"></div>
  <nav class="sidebar" id="sidebar">
    <img class="sidebar-logo" src="../common/one-piece-full-logo.webp" alt="One Piece TCG" />
    <h1>TCG Top Cards</h1>
    <ul>
      {set_nav}
    </ul>
    <div class="grand-total">Grand total: ${grand_total:.2f}</div>
  </nav>

  <main class="main">
    {set_sections}
  </main>

  <!-- Card detail overlay -->
  <div class="overlay-backdrop" id="overlay-backdrop" role="dialog" aria-modal="true">
    <div class="overlay" id="overlay">
      <button class="overlay-close" id="overlay-close" aria-label="Close">✕</button>
      <div class="overlay-img-col">
        <img class="overlay-img" id="ov-img" src="" alt="" />
        <div class="overlay-price price-high" id="ov-price"></div>
      </div>
      <div class="overlay-info-col">
        <div class="overlay-name" id="ov-name"></div>
        <div class="overlay-badges" id="ov-badges"></div>
        <div class="overlay-stats" id="ov-stats"></div>
        <div class="overlay-desc" id="ov-desc"></div>
      </div>
    </div>
  </div>

  <script>
    function updateSection(el) {{
      const slug = el.id.replace('box-price-', '');
      const boxCost = parseFloat(el.value) || 0;
      const details = el.closest('.breakeven-details');
      const ev = parseFloat(details.dataset.ev) || 0;

      const diff    = ev - boxCost;
      const outcome = document.getElementById('be-outcome-' + slug);
      const outVal  = document.getElementById('be-outcome-val-' + slug);
      const boxesEl = document.getElementById('be-boxes-' + slug);

      outcome.classList.remove('be-profit', 'be-loss');
      if (diff >= 0) {{
        outcome.classList.add('be-profit');
        outVal.textContent = '+$' + diff.toFixed(2) + ' profit';
        boxesEl.textContent = '1 box';
      }} else {{
        outcome.classList.add('be-loss');
        outVal.textContent = '-$' + Math.abs(diff).toFixed(2) + ' loss';
        const boxes = ev > 0 ? Math.ceil(boxCost / ev) : '∞';
        boxesEl.textContent = boxes + (boxes !== '∞' ? ' boxes' : '');
      }}
    }}

    document.querySelectorAll('.box-price-input').forEach(input => {{
      input.addEventListener('input', () => updateSection(input));
      updateSection(input);
    }});

    /* ── Card overlay ── */
    const backdrop = document.getElementById('overlay-backdrop');
    const ovClose  = document.getElementById('overlay-close');

    function openOverlay(card) {{
      const d = card.dataset;

      document.getElementById('ov-img').src = d.image;
      document.getElementById('ov-img').alt = d.name;
      document.getElementById('ov-name').textContent = d.name;

      const price = d.price || '';
      const priceEl = document.getElementById('ov-price');
      priceEl.textContent = price;
      const p = parseFloat(price.replace('$',''));
      priceEl.className = 'overlay-price ' + (p >= 50 ? 'price-high' : p >= 10 ? 'price-mid' : 'price-low');

      // Badges
      const badges = document.getElementById('ov-badges');
      badges.innerHTML = '';
      if (d.number)    badges.innerHTML += `<span class="badge">${{d.number}}</span>`;
      if (d.rarityDb)  badges.innerHTML += `<span class="badge rarity">${{d.rarityDb}}</span>`;
      if (d.rarityName) badges.innerHTML += `<span class="rarity-name">${{d.rarityName}}</span>`;
      if (d.color)     badges.innerHTML += `<span class="badge" style="background:#1e2a3a;color:#60a5fa">${{d.color}}</span>`;
      if (d.cardType)  badges.innerHTML += `<span class="badge" style="background:#2a1e3a;color:#c084fc">${{d.cardType}}</span>`;

      // Stats grid
      const stats = [
        ['Cost',      d.cost],
        ['Power',     d.power],
        ['Counter',   d.counter],
        ['Life',      d.life],
        ['Attribute', d.attribute],
        ['Subtypes',  d.subtypes],
      ];
      const statsEl = document.getElementById('ov-stats');
      statsEl.innerHTML = stats
        .filter(([, v]) => v)
        .map(([label, val]) =>
          `<div class="overlay-stat">
            <span class="overlay-stat-label">${{label}}</span>
            <span class="overlay-stat-value">${{val}}</span>
          </div>`
        ).join('');

      // Description (may contain HTML tags from TCGPlayer)
      const descEl = document.getElementById('ov-desc');
      if (d.description) {{
        descEl.innerHTML = d.description;
        descEl.style.display = '';
      }} else {{
        descEl.style.display = 'none';
      }}

      backdrop.classList.add('open');
      document.body.style.overflow = 'hidden';
    }}

    function closeOverlay() {{
      backdrop.classList.remove('open');
      document.body.style.overflow = '';
    }}

    document.querySelectorAll('.card').forEach(card => {{
      card.addEventListener('click', () => openOverlay(card));
      card.addEventListener('keydown', e => {{ if (e.key === 'Enter' || e.key === ' ') openOverlay(card); }});
    }});

    ovClose.addEventListener('click', closeOverlay);
    backdrop.addEventListener('click', e => {{ if (e.target === backdrop) closeOverlay(); }});
    document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeOverlay(); }});

    /* ── Hamburger / sidebar ── */
    const hamburger      = document.getElementById('hamburger');
    const sidebar        = document.getElementById('sidebar');
    const sidebarBackdrop = document.getElementById('sidebar-backdrop');

    function openSidebar() {{
      sidebar.classList.add('open');
      sidebarBackdrop.classList.add('open');
      document.body.style.overflow = 'hidden';
    }}
    function closeSidebar() {{
      sidebar.classList.remove('open');
      sidebarBackdrop.classList.remove('open');
      document.body.style.overflow = '';
    }}

    hamburger.addEventListener('click', openSidebar);
    sidebarBackdrop.addEventListener('click', closeSidebar);
    document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeSidebar(); }});
    sidebar.querySelectorAll('a').forEach(a => a.addEventListener('click', closeSidebar));
  </script>
</body>
</html>"""


def main():
    if not SETS:
        print("No sets defined. Add set name slugs to the SETS array.")
        return

    sets_data = []

    for set_name in SETS:
        print(f"\n{'=' * 60}")
        print(f"Set: {set_name}")
        print(f"{'=' * 60}")

        try:
            cards = fetch_top_cards(set_name)
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
        card_rows = []
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
            card_rows.append({
                "name":        name,
                "price":       price,
                "product_id":  info["productId"],
                "number":      info["number"],
                "rarity_db":   info["rarityDbName"],
                "rarity_name": info["rarityName"],
                "image_url":   card_image_url(info["productId"]),
                "card_type":   info["cardType"],
                "life":        info["life"],
                "counter":     info["counter"],
                "power":       info["power"],
                "cost":        info["cost"],
                "subtypes":    info["subtypes"],
                "attribute":   info["attribute"],
                "color":       info["color"],
                "description": info["description"],
            })

        avg = total / len(card_rows) if card_rows else 0.0
        print(f"\n  Top {len(card_rows)} cards total value:  ${total:.2f}")
        print(f"  Average price:              ${avg:.2f}")

        # Derive a display name from the slug
        display_name = result.get("setName", set_name.replace("-", " ").title())
        sets_data.append({
            "slug":  set_name,
            "name":  display_name,
            "cards": card_rows,
            "total": total,
            "avg":   avg,
        })

    if sets_data:
        html = build_html(sets_data)
        with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML report saved to: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
