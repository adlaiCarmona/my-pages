import requests
import json
import os
import argparse
from datetime import datetime, timezone

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


def fetch_top_cards(set_name: str, force_fetch: bool = False) -> list[dict]:
    path = cache_path(set_name)

    if not force_fetch and os.path.exists(path):
        print(f"  (loaded from cache: {path})")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        if force_fetch:
            print(f"  (force fetch — skipping cache)")
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
PRICE_HISTORY_FILE = os.path.join(_HERE, "price_history.json")

# Maps set slug → set ID prefix (e.g. "OP01").
# Slugs not listed here (or mapped to "") will show no prefix.
SET_IDS = {
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
    # Extra boosters — add IDs when known
    "extra-booster-anime-25th-collection":          "EB02",
    "extra-booster-one-piece-heroines-edition":     "EB03",
}


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


def load_price_history() -> dict:
    """Load the previous price snapshot. Returns dict: {product_id_str: {"price": float, "scan_date": str}}"""
    if os.path.exists(PRICE_HISTORY_FILE):
        with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_price_history(sets_data: list[dict], scan_date: str) -> None:
    """Save current prices, ranks, and set totals keyed by product_id for next-run comparison."""
    history = {}
    # Per-card entries
    for s in sets_data:
        for card in s["cards"]:
            pid = str(int(card["product_id"])) if card["product_id"] else ""
            if pid:
                history[pid] = {
                    "price": card["price"],
                    "rank": card["rank"],
                    "name": card["name"],
                    "scan_date": scan_date,
                }
    # Per-set totals stored under a reserved key
    history["_sets"] = {
        s["slug"]: {"total": s["total"], "scan_date": scan_date}
        for s in sets_data
    }
    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
    print(f"  Price history saved to: {PRICE_HISTORY_FILE}")


def build_html(sets_data: list[dict], last_scan_date: str | None = None) -> str:
    def total_delta_nav(s):
        tc = s.get("total_change")
        if tc is None or tc == 0:
            return ""
        cls = "total-delta-up" if tc > 0 else "total-delta-down"
        sign = "+" if tc > 0 else ""
        return f'<span class="nav-total-delta {cls}">{sign}${tc:.2f}</span>'

    set_nav = "\n".join(
        f'<li><a href="#{s["slug"]}">{s["name"]}</a>'
        f'<span class="nav-total">${s["total"]:.2f}{total_delta_nav(s)}</span></li>'
        for s in sets_data
    )

    set_sections = ""
    for s in sets_data:
        cards_html = ""
        for i, card in enumerate(s["cards"], start=1):
            price_cls = "price-high" if card["price"] >= 50 else ("price-mid" if card["price"] >= 10 else "price-low")
            import html as _html
            desc_escaped = _html.escape(card['description'], quote=True)

            # Price change badge
            delta = card.get("price_change")
            if delta is None:
                delta_html = ""
                delta_data = ""
            elif delta > 0:
                delta_html = f'<div class="price-delta delta-up">▲ ${delta:.2f}</div>'
                delta_data = f"data-price-change=\"+{delta:.2f}\""
            elif delta < 0:
                delta_html = f'<div class="price-delta delta-down">▼ ${abs(delta):.2f}</div>'
                delta_data = f"data-price-change=\"{delta:.2f}\""
            else:
                delta_html = '<div class="price-delta delta-flat">— no change</div>'
                delta_data = "data-price-change=\"0\""

            # Rank change badge
            rc = card.get("rank_change")
            if rc is None:
                rank_delta_html = '<div class="rank-delta rank-new">NEW</div>'
                rank_data = "data-rank-change=\"new\""
            elif rc > 0:
                rank_delta_html = f'<div class="rank-delta rank-up">▲ {rc} rank</div>'
                rank_data = f"data-rank-change=\"+{rc}\""
            elif rc < 0:
                rank_delta_html = f'<div class="rank-delta rank-down">▼ {abs(rc)} rank</div>'
                rank_data = f"data-rank-change=\"{rc}\""
            else:
                rank_delta_html = ""
                rank_data = "data-rank-change=\"0\""
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
          {delta_data}
          {rank_data}
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
            {delta_html}
            {rank_delta_html}
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

        # ── Rarity filter tags for this set ────────────────────────
        RARITY_ORDER = ["C", "UC", "R", "SR", "SEC", "SP", "L", "PR", "TR", "DON!!"]
        present_rarities = []
        seen = set()
        for r in RARITY_ORDER:
            if any(c["rarity_db"] == r for c in s["cards"]) and r not in seen:
                present_rarities.append(r)
                seen.add(r)
        # also catch any unknown rarities not in the ordered list
        for c in s["cards"]:
            r = c["rarity_db"] or ""
            if r and r not in seen:
                present_rarities.append(r)
                seen.add(r)

        rarity_tags_html = "".join(
            f'<button class="rf-tag active" data-r="{r}" data-slug="{s["slug"]}">{r}</button>'
            for r in present_rarities
        )

        tc = s.get("total_change")
        if tc is not None and tc != 0:
            tc_cls = "total-delta total-delta-up" if tc > 0 else "total-delta total-delta-down"
            tc_sign = "+" if tc > 0 else ""
            total_change_html = f'<span class="{tc_cls}">({tc_sign}${tc:.2f})</span>'
        else:
            total_change_html = ""

        set_sections += f"""
  <section class="set-section" id="{s['slug']}">
    <div class="set-header">
      <h2>{s['name']}</h2>
      <div class="set-stats">
        <span>Top {len(s['cards'])} cards</span>
        <span class="set-total">Total: ${s['total']:.2f} {total_change_html}</span>
        <span class="set-avg">Avg: ${s['avg']:.2f}</span>
      </div>
      <div class="rarity-filters" data-slug="{s['slug']}">{rarity_tags_html}</div>
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

    last_scan_html = ""
    if last_scan_date:
        last_scan_html = f'<div class="last-scan">Last price scan:<br>{last_scan_date}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TCG Top Cards</title>
  <link rel="shortcut icon" type="image/x-icon" href="../favicon.ico">
  <link rel="stylesheet" href="style.css" />
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
    {last_scan_html}
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
        <div class="price-delta" id="ov-delta" style="display:none;text-align:center;"></div>
        <div class="rank-delta" id="ov-rank-delta" style="display:none;text-align:center;"></div>
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

      // Price change
      const deltaEl = document.getElementById('ov-delta');
      if (d.priceChange !== undefined && d.priceChange !== '') {{
        const dv = parseFloat(d.priceChange);
        if (dv > 0) {{
          deltaEl.textContent = '▲ $' + dv.toFixed(2) + ' since last scan';
          deltaEl.className = 'price-delta delta-up';
        }} else if (dv < 0) {{
          deltaEl.textContent = '▼ $' + Math.abs(dv).toFixed(2) + ' since last scan';
          deltaEl.className = 'price-delta delta-down';
        }} else {{
          deltaEl.textContent = '— no change since last scan';
          deltaEl.className = 'price-delta delta-flat';
        }}
        deltaEl.style.display = '';
      }} else {{
        deltaEl.textContent = '';
        deltaEl.style.display = 'none';
      }}

      // Rank change
      const rankEl = document.getElementById('ov-rank-delta');
      const rc = d.rankChange;
      if (rc === 'new') {{
        rankEl.textContent = 'NEW to ranking';
        rankEl.className = 'rank-delta rank-new';
        rankEl.style.display = '';
      }} else if (rc !== undefined && rc !== '' && rc !== '0') {{
        const rv = parseInt(rc, 10);
        if (rv > 0) {{
          rankEl.textContent = '▲ ' + rv + ' rank';
          rankEl.className = 'rank-delta rank-up';
        }} else {{
          rankEl.textContent = '▼ ' + Math.abs(rv) + ' rank';
          rankEl.className = 'rank-delta rank-down';
        }}
        rankEl.style.display = '';
      }} else {{
        rankEl.textContent = '';
        rankEl.style.display = 'none';
      }}

      // Badges
      const badges = document.getElementById('ov-badges');
      badges.innerHTML = '';
      if (d.number)    badges.innerHTML += `<span class="badge">${{d.number}}</span>`;
      if (d.rarityDb)  badges.innerHTML += `<span class="badge rarity">${{d.rarityDb}}</span>`;
      if (d.rarityName) badges.innerHTML += `<span class="rarity-name">${{d.rarityName}}</span>`;
      if (d.color)     badges.innerHTML += `<span class="badge badge-color">${{d.color}}</span>`;
      if (d.cardType)  badges.innerHTML += `<span class="badge badge-type">${{d.cardType}}</span>`;

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

    /* ── Rarity filters ── */
    function applyRarityFilter(slug) {{
      const section = document.getElementById(slug);
      const activeTags = [...document.querySelectorAll(`.rf-tag[data-slug="${{slug}}"].active`)];
      const activeRarities = new Set(activeTags.map(t => t.dataset.r));
      section.querySelectorAll('.card').forEach(card => {{
        const r = card.dataset.rarityDb || '';
        card.style.display = activeRarities.size === 0 || activeRarities.has(r) ? '' : 'none';
      }});
    }}

    document.querySelectorAll('.rf-tag').forEach(tag => {{
      tag.addEventListener('click', () => {{
        tag.classList.toggle('active');
        applyRarityFilter(tag.dataset.slug);
      }});
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
    parser = argparse.ArgumentParser(description="Fetch top One Piece TCG cards and build index.html")
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Ignore cached data and fetch fresh results from the API"
    )
    args = parser.parse_args()
    force_fetch = args.no_cache

    if not SETS:
        print("No sets defined. Add set name slugs to the SETS array.")
        return

    # Load previous price history for comparison
    price_history = load_price_history()
    last_scan_date: str | None = None
    if price_history:
        # Find the most recent scan date across all records
        dates = [v["scan_date"] for v in price_history.values() if "scan_date" in v]
        if dates:
            last_scan_date = max(dates)
        print(f"Loaded price history ({len(price_history)} cards). Last scan: {last_scan_date}")
    else:
        print("No previous price history found — this will be the first baseline.")

    sets_data = []

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
            pid_str = str(int(info["productId"])) if info["productId"] else ""
            prev = price_history.get(pid_str)
            if prev is not None:
                price_change = round(price - prev["price"], 2)
                # rank_change: positive means moved UP (lower number = higher rank)
                prev_rank = prev.get("rank")
                rank_change = (prev_rank - i) if prev_rank is not None else None
            else:
                price_change = None
                rank_change = None
            card_rows.append({
                "name":         name,
                "price":        price,
                "price_change": price_change,
                "rank":         i,
                "rank_change":  rank_change,
                "product_id":   info["productId"],
                "number":       info["number"],
                "rarity_db":    info["rarityDbName"],
                "rarity_name":  info["rarityName"],
                "image_url":    card_image_url(info["productId"]),
                "card_type":    info["cardType"],
                "life":         info["life"],
                "counter":      info["counter"],
                "power":        info["power"],
                "cost":         info["cost"],
                "subtypes":     info["subtypes"],
                "attribute":    info["attribute"],
                "color":        info["color"],
                "description":  info["description"],
            })

        avg = total / len(card_rows) if card_rows else 0.0
        print(f"\n  Top {len(card_rows)} cards total value:  ${total:.2f}")
        print(f"  Average price:              ${avg:.2f}")

        # Set total change vs previous run
        prev_sets = price_history.get("_sets", {})
        prev_set_total = prev_sets.get(set_name, {}).get("total")
        total_change = round(total - prev_set_total, 2) if prev_set_total is not None else None

        # Derive a display name from the slug, prefixed with the set ID if known
        base_name = result.get("setName", set_name.replace("-", " ").title())
        set_id = SET_IDS.get(set_name, "")
        display_name = f"{set_id} – {base_name}" if set_id else base_name
        sets_data.append({
            "slug":         set_name,
            "name":         display_name,
            "cards":        card_rows,
            "total":        total,
            "total_change": total_change,
            "avg":          avg,
        })

    if sets_data:
        def set_sort_key(s):
            sid = SET_IDS.get(s["slug"], "").upper()
            if sid.startswith("OP"):
                return (0, sid)
            elif sid.startswith("EB"):
                return (1, sid)
            elif sid:
                return (2, sid)
            else:
                return (3, s["slug"])

        sets_data.sort(key=set_sort_key)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        html = build_html(sets_data, last_scan_date=last_scan_date)
        with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML report saved to: {OUTPUT_HTML}")

        save_price_history(sets_data, now_str)
        print(f"Price history updated at: {now_str}")


if __name__ == "__main__":
    main()
