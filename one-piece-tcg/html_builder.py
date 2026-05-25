"""HTML generation helpers for the One Piece TCG price tracker."""
import html as _html
import json
import os
import re

from constants import PRICE_BUCKETS, RARITY_ORDER, SET_IDS

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_HERE, "template.html")

# ── Hit classification ───────────────────────────────────────────────────────

_HIT_SUFFIXES = re.compile(r'\((SP|Manga|Alternate Art)\)', re.IGNORECASE)


def _is_hit(card: dict) -> bool:
    return bool(_HIT_SUFFIXES.search(card["name"])) or card["rarity_db"] == "SEC"


def _hit_type(card: dict) -> str:
    if re.search(r'\(Manga\)', card["name"], re.IGNORECASE):
        return "Manga"
    if re.search(r'\(Alternate Art\)', card["name"], re.IGNORECASE):
        return "Alt Art"
    if re.search(r'\(SP\)', card["name"], re.IGNORECASE):
        return "SP"
    return "SEC"


# ── Price bucket chart ───────────────────────────────────────────────────────

_BUCKET_COLORS = ["#34d399", "#a3e635", "#fbbf24", "#fb923c", "#f87171", "#c084fc"]


def _price_bucket_counts(cards: list[dict]) -> list[tuple[str, int]]:
    results = []
    for lo, hi, label in PRICE_BUCKETS:
        count = sum(
            1 for c in cards
            if c["price"] >= lo and (hi is None or c["price"] < hi)
        )
        results.append((label, count))
    return results


def _price_distribution_html(cards: list[dict]) -> tuple[str, str]:
    """Return (chart_bars_html, summary_pills_html)."""
    buckets = _price_bucket_counts(cards)
    max_count = max((c for _, c in buckets), default=1) or 1
    chart_bars = ""
    summary_pills = ""
    for idx, (label, count) in enumerate(buckets):
        pct = round(count / max_count * 100)
        color = _BUCKET_COLORS[idx % len(_BUCKET_COLORS)]
        empty_cls = "" if count else " bucket-empty"
        chart_bars += (
            f'\n              <div class="bar-group">'
            f'<div class="bar-wrap">'
            f'<span class="bar-val">{count}</span>'
            f'<div class="bar" style="height:{pct}%;background:{color};"></div>'
            f'</div>'
            f'<div class="bar-label">{label}</div>'
            f'</div>'
        )
        summary_pills += (
            f'<div class="bucket{empty_cls}">'
            f'<span class="bucket-label">{label}</span>'
            f'<span class="bucket-count" style="color:{color if count else "#44445a"}">{count}</span>'
            f'</div>'
        )
    return chart_bars, summary_pills


# ── Breakeven panel ──────────────────────────────────────────────────────────

def _breakeven_html(cards: list[dict], slug: str) -> tuple[str, float]:
    """Return (breakeven_panel_html, ev_per_box)."""
    hits       = [c for c in cards if _is_hit(c)]
    manga_hits = [c for c in hits if re.search(r'\(Manga\)', c["name"], re.IGNORECASE)]
    alt_hits   = [c for c in hits if re.search(r'\(Alternate Art\)', c["name"], re.IGNORECASE)]
    sp_hits    = [c for c in hits if re.search(r'\(SP\)', c["name"], re.IGNORECASE)]
    sec_hits   = [
        c for c in hits
        if c["rarity_db"] == "SEC" and not re.search(r'\((SP|Manga|Alternate Art)\)', c["name"], re.IGNORECASE)
    ]

    normal_hits     = sp_hits + sec_hits + alt_hits
    avg_normal_hit  = (sum(c["price"] for c in normal_hits) / len(normal_hits)) if normal_hits else 0.0
    avg_manga_hit   = (sum(c["price"] for c in manga_hits) / len(manga_hits)) if manga_hits else 0.0
    ev_per_box      = 2 * avg_normal_hit + 0.2 * avg_manga_hit

    def _avg_str(items):
        return f'${sum(c["price"] for c in items) / len(items):.2f} avg' if items else "—"

    panel = f"""
      <div class="box-price-row">
        <label for="box-price-{slug}">Booster box price:</label>
        <input id="box-price-{slug}" class="box-price-input" type="number" min="0" step="0.01" value="350" />
      </div>
      <div class="be-grid">
        <div class="be-stat"><span class="be-label">SP hits ({len(sp_hits)})</span><span class="be-value">{_avg_str(sp_hits)}</span></div>
        <div class="be-stat"><span class="be-label">Alternate Art hits ({len(alt_hits)})</span><span class="be-value">{_avg_str(alt_hits)}</span></div>
        <div class="be-stat"><span class="be-label">SEC hits ({len(sec_hits)})</span><span class="be-value">{_avg_str(sec_hits)}</span></div>
        <div class="be-stat"><span class="be-label">Manga hits ({len(manga_hits)}, 1-in-5 boxes)</span><span class="be-value">{f'${avg_manga_hit:.2f} avg' if manga_hits else '—'}</span></div>
        <div class="be-stat"><span class="be-label">Avg normal hit value</span><span class="be-value">${avg_normal_hit:.2f}</span></div>
        <div class="be-stat"><span class="be-label">Expected value / box</span><span class="be-value be-ev">${ev_per_box:.2f}</span></div>
      </div>
      <div class="be-result-row">
        <div class="be-result-box">
          <span class="be-result-label">Expected value</span>
          <span class="be-result-value be-ev-display" id="be-ev-{slug}">${ev_per_box:.2f}</span>
        </div>
        <div class="be-result-box be-outcome-box" id="be-outcome-{slug}">
          <span class="be-result-label">Outcome</span>
          <span class="be-result-value" id="be-outcome-val-{slug}">—</span>
        </div>
        <div class="be-result-box">
          <span class="be-result-label">Boxes to break even</span>
          <span class="be-result-value" id="be-boxes-{slug}">—</span>
        </div>
      </div>"""
    return panel, ev_per_box


# ── Card HTML ────────────────────────────────────────────────────────────────

def _price_delta_html(delta) -> tuple[str, str]:
    """Return (badge_html, data_attr_string)."""
    if delta is None:
        return "", ""
    if delta > 0:
        return (
            f'<div class="price-delta delta-up">▲ ${delta:.2f}</div>',
            f'data-price-change="+{delta:.2f}"',
        )
    if delta < 0:
        return (
            f'<div class="price-delta delta-down">▼ ${abs(delta):.2f}</div>',
            f'data-price-change="{delta:.2f}"',
        )
    return '<div class="price-delta delta-flat">— no change</div>', 'data-price-change="0"'


def _rank_delta_html(rc) -> tuple[str, str]:
    """Return (badge_html, data_attr_string)."""
    if rc is None:
        return '<div class="rank-delta rank-new">NEW</div>', 'data-rank-change="new"'
    if rc > 0:
        return f'<div class="rank-delta rank-up">▲ {rc} rank</div>', f'data-rank-change="+{rc}"'
    if rc < 0:
        return f'<div class="rank-delta rank-down">▼ {abs(rc)} rank</div>', f'data-rank-change="{rc}"'
    return "", 'data-rank-change="0"'


def _card_html(card: dict, rank: int) -> str:
    price_cls = "price-high" if card["price"] >= 50 else ("price-mid" if card["price"] >= 10 else "price-low")
    desc_escaped = _html.escape(card["description"], quote=True)
    delta_html, delta_data     = _price_delta_html(card.get("price_change"))
    rank_html, rank_data       = _rank_delta_html(card.get("rank_change"))
    pid_int = int(card["product_id"]) if card["product_id"] else ""

    return f"""
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
          data-product-id="{pid_int}"
          {delta_data}
          {rank_data}
        >
          <div class="card-rank">#{rank}</div>
          <img class="card-img" src="{card['image_url']}" alt="{card['name']}" loading="lazy" />
          <div class="card-body">
            <div class="card-name">{card['name']}</div>
            <div class="card-meta">
              <span class="badge">{card['number'] or '—'}</span>
              <span class="badge rarity">{card['rarity_db'] or '—'}</span>
              <span class="rarity-name">{card['rarity_name'] or '—'}</span>
            </div>
            <div class="card-id">ID: {pid_int or 'N/A'}</div>
            <div class="card-price {price_cls}">${card['price']:.2f}</div>
            {delta_html}
            {rank_html}
          </div>
        </div>"""


# ── Rarity filter tags ───────────────────────────────────────────────────────

def _rarity_tags_html(cards: list[dict], slug: str) -> str:
    seen: set[str] = set()
    present: list[str] = []
    for r in RARITY_ORDER:
        if any(c["rarity_db"] == r for c in cards) and r not in seen:
            present.append(r)
            seen.add(r)
    for c in cards:
        r = c["rarity_db"] or ""
        if r and r not in seen:
            present.append(r)
            seen.add(r)
    return "".join(
        f'<button class="rf-tag active" data-r="{r}" data-slug="{slug}">{r}</button>'
        for r in present
    )


# ── Set section ──────────────────────────────────────────────────────────────

def _set_section_html(s: dict) -> str:
    cards_html    = "".join(_card_html(c, i) for i, c in enumerate(s["cards"], start=1))
    chart_bars, summary_pills = _price_distribution_html(s["cards"])
    breakeven_panel, ev_per_box = _breakeven_html(s["cards"], s["slug"])
    rarity_tags   = _rarity_tags_html(s["cards"], s["slug"])

    tc = s.get("total_change")
    if tc is not None and tc != 0:
        tc_cls  = "total-delta total-delta-up" if tc > 0 else "total-delta total-delta-down"
        tc_sign = "+" if tc > 0 else ""
        total_change_html = f'<span class="{tc_cls}">({tc_sign}${tc:.2f})</span>'
    else:
        total_change_html = ""

    return f"""
  <section class="set-section" id="{s['slug']}">
    <div class="set-header">
      <h2>{s['name']}</h2>
      <div class="set-stats">
        <span>Top {len(s['cards'])} cards</span>
        <span class="set-total">Total: ${s['total']:.2f} {total_change_html}</span>
        <span class="set-avg">Avg: ${s['avg']:.2f}</span>
      </div>
      <div class="rarity-filters" data-slug="{s['slug']}">{rarity_tags}</div>
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
      <div class="breakeven-panel">{breakeven_panel}
      </div>
    </details>
    <div class="cards-grid">
      {cards_html}
    </div>
  </section>"""


# ── Sidebar nav ──────────────────────────────────────────────────────────────

def _set_nav_html(sets_data: list[dict]) -> str:
    items = []
    for s in sets_data:
        tc = s.get("total_change")
        if tc is not None and tc != 0:
            cls  = "total-delta-up" if tc > 0 else "total-delta-down"
            sign = "+" if tc > 0 else ""
            delta_span = f'<span class="nav-total-delta {cls}">{sign}${tc:.2f}</span>'
        else:
            delta_span = ""
        items.append(
            f'<li><a href="#{s["slug"]}">{s["name"]}</a>'
            f'<span class="nav-total">${s["total"]:.2f}{delta_span}</span></li>'
        )
    return "\n".join(items)


# ── Main entry point ─────────────────────────────────────────────────────────

def build_html(sets_data: list[dict], last_scan_date: str | None = None) -> str:
    """Render the full HTML page from *sets_data* and return it as a string."""
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    grand_total = sum(s["total"] for s in sets_data)

    # Inline price history JS map
    ph_map: dict = {}
    for s in sets_data:
        for card in s["cards"]:
            ph = card.get("price_history")
            if ph and card["product_id"]:
                ph_map[str(int(card["product_id"]))] = ph
    ph_json = json.dumps(ph_map, separators=(",", ":"))

    last_scan_html = (
        f'<div class="last-scan">Last price scan:<br>{last_scan_date}</div>'
        if last_scan_date else ""
    )

    return template.format(
        set_nav=_set_nav_html(sets_data),
        set_sections="".join(_set_section_html(s) for s in sets_data),
        grand_total=f"${grand_total:.2f}",
        last_scan_html=last_scan_html,
        price_history_json=ph_json,
    )
