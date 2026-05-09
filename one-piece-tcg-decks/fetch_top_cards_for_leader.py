#!/usr/bin/env python3
"""
Fetch top cards used across tournament decklists for each leader in leaders.json.

For each leader card ID:
  1. Scrape decklists from https://onepiece.limitlesstcg.com/cards/{id}/decklists
  2. For each deck URL, scrape all cards grouped by type
  3. Aggregate counts across all decks and compute usage percentages
  4. Output a JSON file per leader under cache/{leader_id}.json
  5. Generate index.html in the same folder with a visual breakdown
"""

import html as html_module
import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from card_info import get_card_info

BASE_URL = "https://onepiece.limitlesstcg.com"
CDN_BASE = "https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/one-piece"
CACHE_DIR = Path(__file__).parent / "cache"
DECKLIST_CACHE_DIR = CACHE_DIR / "decklists"
LEADERS_FILE = Path(__file__).parent / "leaders.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_DELAY = 0.5  # seconds between requests to be polite


def get_html(url: str) -> BeautifulSoup:
    """Fetch a URL and return a BeautifulSoup object."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return BeautifulSoup(resp.text, "html.parser")


def _deck_cache_path(deck_url: str) -> Path:
    """Return the cache file path for a given deck URL."""
    key = hashlib.sha1(deck_url.encode()).hexdigest()
    return DECKLIST_CACHE_DIR / f"{key}.json"


def load_cached_decklist(deck_url: str) -> dict | None:
    """Return the cached parsed decklist for *deck_url*, or None if not cached."""
    path = _deck_cache_path(deck_url)
    if path.exists():
        return json.loads(path.read_text())
    return None


def save_cached_decklist(deck_url: str, data: dict) -> None:
    """Persist a parsed decklist to the deck-level cache."""
    DECKLIST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _deck_cache_path(deck_url).write_text(json.dumps(data, ensure_ascii=False))


def card_image_url(card_id: str) -> str:
    """
    Build the CDN image URL for a card.
    e.g. OP06-022  ->  .../one-piece/OP06/OP06-022_EN.webp
         ST28-005  ->  .../one-piece/ST28/ST28-005_EN.webp
    """
    # The set prefix is everything before the last hyphen group of digits
    match = re.match(r"^([A-Z0-9]+)-(\d+)$", card_id, re.IGNORECASE)
    if not match:
        return ""
    set_code = match.group(1).upper()
    return f"{CDN_BASE}/{set_code}/{card_id.upper()}_EN.webp"


def get_deck_urls_for_leader(leader_id: str) -> list[str]:
    """Return all deck list URLs from the leader's decklists page."""
    url = f"{BASE_URL}/cards/{leader_id}/decklists"
    soup = get_html(url)

    table = soup.find("table", class_="data-table")
    if not table:
        print(f"  [warn] No data-table found for {leader_id}")
        return []

    urls = []
    seen = set()
    for a in table.find_all("a", href=True):
        href = a["href"]
        if "/decks/list/" in href:
            # Normalise to absolute URL
            full = href if href.startswith("http") else BASE_URL + href
            if full not in seen:
                seen.add(full)
                urls.append(full)

    return urls


def parse_decklist(deck_url: str) -> dict:
    """
    Parse a deck page and return a dict:
      {
        "card_type": [
          {"card_id": ..., "card_name": ..., "count": ..., "image_url": ...},
          ...
        ],
        ...
      }
    """
    soup = get_html(deck_url)

    # Only look inside the text decklist section (not the image section which
    # duplicates everything).
    text_section = soup.find(attrs={"data-text-decklist": True})
    if not text_section:
        text_section = soup  # fallback

    result = {}
    columns = text_section.find_all("div", class_="decklist-column")
    for col in columns:
        heading_el = col.find("div", class_="decklist-column-heading")
        if not heading_el:
            continue
        # Heading looks like "Character (49)" or "Leader" or "Event (1)"
        heading_text = heading_el.get_text(strip=True)
        card_type = re.sub(r"\s*\(\d+\)\s*$", "", heading_text).strip()

        cards = []
        for card_div in col.find_all("div", class_="decklist-card"):
            card_link = card_div.find("a", class_="card-link")
            if not card_link:
                continue

            name_span = card_link.find("span", class_="card-name")
            if not name_span:
                continue

            raw_name = name_span.get_text(strip=True)
            # Raw name format: "Yamato (OP06-022)"
            name_match = re.match(r"^(.+?)\s*\(([^)]+)\)$", raw_name)
            if name_match:
                card_name = name_match.group(1).strip()
                card_id = name_match.group(2).strip()
            else:
                card_name = raw_name
                card_id = card_div.get("data-id", "")

            # Count from data attribute (more reliable than the span text)
            count = int(card_div.get("data-count", 1))

            cards.append(
                {
                    "card_id": card_id,
                    "card_name": card_name,
                    "count": count,
                    "image_url": card_image_url(card_id),
                }
            )

        if cards:
            result[card_type] = result.get(card_type, []) + cards

    return result


def aggregate_stats(all_decklists: list[dict]) -> dict:
    """
    Given a list of parsed decklists (one per deck), compute per-card stats:
      - total_copies: sum of all copies across every deck
      - decks_with_card: how many decks include at least 1 copy
      - avg_copies_when_played: average copies in decks that run it
      - usage_pct: percentage of decks that include the card
    Returns a dict keyed by card_type, then sorted by usage_pct desc.
    """
    total_decks = len(all_decklists)
    if total_decks == 0:
        return {}

    # Accumulate per card_type -> card_id -> stats
    # card_type -> card_id -> {name, image_url, copies_per_deck: []}
    type_card_data: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))

    for deck in all_decklists:
        for card_type, cards in deck.items():
            for card in cards:
                cid = card["card_id"]
                entry = type_card_data[card_type][cid]
                if not entry:
                    entry["card_id"] = cid
                    entry["card_name"] = card["card_name"]
                    entry["image_url"] = card["image_url"]
                    entry["copies_per_deck"] = []
                entry["copies_per_deck"].append(card["count"])

    output = {}
    for card_type, cards_map in type_card_data.items():
        cards_list = []
        for cid, data in cards_map.items():
            copies = data["copies_per_deck"]
            decks_with = len(copies)
            total_copies = sum(copies)
            avg_copies = round(total_copies / decks_with, 2)
            usage_pct = round(decks_with / total_decks * 100, 1)

            cards_list.append(
                {
                    "card_id": cid,
                    "card_name": data["card_name"],
                    "image_url": data["image_url"],
                    "total_copies": total_copies,
                    "decks_with_card": decks_with,
                    "total_decks": total_decks,
                    "avg_copies_when_played": avg_copies,
                    "usage_pct": usage_pct,
                }
            )

        # Sort by usage_pct descending, then avg copies descending
        cards_list.sort(key=lambda c: (-c["usage_pct"], -c["avg_copies_when_played"]))
        output[card_type] = cards_list

    # ── Enrich every unique card with API metadata ────────────────────────────
    seen_ids: set[str] = set()
    for cards_list in output.values():
        for card in cards_list:
            cid = card["card_id"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            info = get_card_info(cid)
            if info:
                card.update(info)
            else:
                # Ensure keys always exist so templates don't need to guard
                for field in (
                    "market_price", "rarity", "card_text", "card_color",
                    "card_type", "card_cost", "card_power", "sub_types",
                    "counter_amount", "attribute",
                ):
                    card.setdefault(field, None)

    return output


def _da(value) -> str:
    """Render a data-attribute value: empty string when None."""
    if value is None:
        return ""
    return html_module.escape(str(value), quote=True)


def slug(text: str) -> str:
    """Turn a card name / ID into a safe HTML id attribute."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def pct_color(pct: float) -> str:
    """Return a CSS colour that maps 0-100 % onto red→yellow→green."""
    if pct >= 80:
        return "#34d399"   # green
    if pct >= 50:
        return "#a3e635"   # lime
    if pct >= 25:
        return "#fbbf24"   # amber
    return "#f87171"       # red


def build_html(all_results: list[dict]) -> str:
    """
    Render index.html content for all processed leaders.
    `all_results` is a list of dicts returned by process_leader (with skipped
    leaders absent).
    """

    # ── sidebar nav items ────────────────────────────────────────────────────
    nav_items = ""
    for r in all_results:
        leader = r["leader"]          # card entry from Leader type
        section_id = slug(r["leader_id"])
        nav_items += (
            f'      <li>'
            f'<a href="#{section_id}">{html_module.escape(leader["card_name"])}'
            f' <span class="nav-card-id">({r["leader_id"]})</span></a>'
            f'<span class="nav-total">{r["total_decks"]} decks</span>'
            f'</li>\n'
        )

    # ── per-leader sections ───────────────────────────────────────────────────
    sections = ""
    for r in all_results:
        leader      = r["leader"]
        leader_id   = r["leader_id"]
        total_decks = r["total_decks"]
        card_stats  = r["card_stats"]
        section_id  = slug(leader_id)

        # Leader card hero
        leader_html = f"""
    <div class="leader-hero">
      <img class="leader-img card-trigger" src="{leader['image_url']}"
           alt="{html_module.escape(leader['card_name'])}" loading="lazy"
           role="button" tabindex="0"
           data-image="{leader['image_url']}"
           data-name="{html_module.escape(leader['card_name'])}"
           data-id="{leader_id}"
           data-usage="100"
           data-avg="1.0"
           data-decks="{total_decks}"
           data-total="{total_decks}"
           data-market-price="{_da(leader.get('market_price'))}"
           data-rarity="{_da(leader.get('rarity'))}"
           data-card-text="{_da(leader.get('card_text'))}"
           data-card-color="{_da(leader.get('card_color'))}"
           data-card-type="{_da(leader.get('card_type'))}"
           data-card-cost="{_da(leader.get('card_cost'))}"
           data-card-power="{_da(leader.get('card_power'))}"
           data-sub-types="{_da(leader.get('sub_types'))}"
           data-counter-amount="{_da(leader.get('counter_amount'))}"
           data-attribute="{_da(leader.get('attribute'))}">
      <div class="leader-meta">
        <h2>{html_module.escape(leader['card_name'])}</h2>
        <span class="badge">{leader_id}</span>
        <span class="deck-count">{total_decks} tournament deck{'' if total_decks == 1 else 's'} analysed</span>
      </div>
    </div>"""

        # One sub-section per card type (skip Leader itself)
        type_sections = ""
        TYPE_ORDER = ["Character", "Event", "Stage", "DON!!"]
        all_types = list(card_stats.keys())
        ordered_types = [t for t in TYPE_ORDER if t in all_types] + \
                        [t for t in all_types if t not in TYPE_ORDER]

        for card_type in ordered_types:
            cards = card_stats[card_type]
            # cost distribution chart: aggregate total_copies by card_cost × card_color
            # Fixed order: bottom → top of each stacked bar
            COLOR_ORDER = [
                ("red",    "#d3171b"),
                ("green",  "#018761"),
                ("blue",   "#0078aa"),
                ("purple", "#6a3677"),
                ("black",  "#000000"),
                ("yellow", "#f6e846"),
                ("multi",  "#ffffff"),
                ("unknown","#a78bfa"),
            ]
            COLOR_NAME_TO_HEX = {name: hex_ for name, hex_ in COLOR_ORDER}
            HEX_TO_NAME = {hex_: name for name, hex_ in COLOR_ORDER}
            KNOWN_COLORS = {name for name, _ in COLOR_ORDER[:6]}  # red..yellow

            # cost_color_totals[cost_key][color_name] = total_copies
            cost_color_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for c in cards:
                cost = c.get("card_cost")
                cost_key = str(cost) if cost is not None and cost != "" else "?"
                raw_color = (c.get("card_color") or "").strip()
                color_parts = [p.strip().lower() for p in re.split(r"[/,;]", raw_color) if p.strip()]
                if len(color_parts) == 1 and color_parts[0] in KNOWN_COLORS:
                    color_name = color_parts[0]
                elif color_parts:
                    color_name = "multi"
                else:
                    color_name = "unknown"
                cost_color_totals[cost_key][color_name] += c["total_copies"]

            # Sort by cost numerically (unknown costs go last)
            def cost_sort_key(k):
                try:
                    return (0, int(k))
                except (ValueError, TypeError):
                    return (1, k)

            sorted_costs = sorted(cost_color_totals.items(), key=lambda x: cost_sort_key(x[0]))
            max_count = max((sum(color_map.values()) for _, color_map in sorted_costs), default=1)

            bar_items = ""
            for cost_key, color_map in sorted_costs:
                total_count = sum(color_map.values())
                bar_h = max(4, round(total_count / max_count * 120))
                # Build stacked segments in fixed order (bottom → top)
                segments = ""
                for color_name, color_hex in COLOR_ORDER:
                    copies = color_map.get(color_name, 0)
                    if copies == 0:
                        continue
                    seg_h = max(1, round(copies / total_count * bar_h))
                    label = color_name.capitalize()
                    tip = f"{label}: {copies} cop{'y' if copies == 1 else 'ies'}"
                    border = "border:1px solid rgba(255,255,255,0.25);" if color_hex in ("#000000", "#ffffff") else ""
                    segments += (
                        f'<div class="bar-seg" data-tip="{html_module.escape(tip)}" '
                        f'style="height:{seg_h}px;background:{color_hex};width:100%;{border}"></div>'
                    )
                bar_items += f"""
              <div class="bar-group">
                <div class="bar-wrap">
                  <span class="bar-val">{total_count}</span>
                  <div class="bar" style="height:{bar_h}px;overflow:hidden;display:flex;flex-direction:column-reverse;border-radius:4px 4px 0 0;">{segments}</div>
                </div>
                <div class="bar-label">Cost {html_module.escape(cost_key)}</div>
              </div>"""

            # Card grid
            card_items = ""
            for rank, c in enumerate(cards, 1):
                colour = pct_color(c["usage_pct"])
                avg_label = f"×{c['avg_copies_when_played']:.1f} avg"
                card_items += f"""
        <div class="card" role="button" tabindex="0"
          data-image="{c['image_url']}"
          data-name="{html_module.escape(c['card_name'])}"
          data-id="{c['card_id']}"
          data-usage="{c['usage_pct']}"
          data-avg="{c['avg_copies_when_played']}"
          data-decks="{c['decks_with_card']}"
          data-total="{total_decks}"
          data-market-price="{_da(c.get('market_price'))}"
          data-rarity="{_da(c.get('rarity'))}"
          data-card-text="{_da(c.get('card_text'))}"
          data-card-color="{_da(c.get('card_color'))}"
          data-card-type="{_da(c.get('card_type'))}"
          data-card-cost="{_da(c.get('card_cost'))}"
          data-card-power="{_da(c.get('card_power'))}"
          data-sub-types="{_da(c.get('sub_types'))}"
          data-counter-amount="{_da(c.get('counter_amount'))}"
          data-attribute="{_da(c.get('attribute'))}"
        >
          <div class="card-rank">#{rank}</div>
          <img class="card-img" src="{c['image_url']}"
               alt="{html_module.escape(c['card_name'])}" loading="lazy">
          <div class="card-body">
            <div class="card-name">{html_module.escape(c['card_name'])}</div>
            <div class="card-meta">
              <span class="badge">{c['card_id']}</span>
              <span class="badge avg-badge">{avg_label}</span>
            </div>
            <div class="usage-bar-wrap">
              <div class="usage-bar" style="width:{c['usage_pct']}%;background:{colour};"></div>
            </div>
            <div class="usage-label" style="color:{colour};">{c['usage_pct']}% of decks</div>
          </div>
        </div>"""

            chart_id = slug(f"{leader_id}-{card_type}-chart")
            type_sections += f"""
    <div class="type-section">
      <h3 class="type-heading">{html_module.escape(card_type)}</h3>
      <details class="chart-details" id="{chart_id}">
        <summary class="chart-toggle">Cost distribution</summary>
        <div class="chart">
          <div class="chart-bars">{bar_items}
          </div>
        </div>
      </details>
      <div class="cards-grid">{card_items}
      </div>
    </div>"""

        sections += f"""
  <section class="leader-section" id="{section_id}">
    <div class="section-header">
      {leader_html}
    </div>
    {type_sections}
  </section>
"""

    # ── overlay markup ────────────────────────────────────────────────────────
    overlay = """
  <div class="bar-tooltip" id="bar-tooltip"></div>

  <div class="overlay-backdrop" id="overlay">
    <div class="overlay">
      <button class="overlay-close" id="overlay-close">✕</button>
      <div class="overlay-img-col">
        <img class="overlay-img" id="overlay-img" src="" alt="">
      </div>
      <div class="overlay-info-col">
        <div class="overlay-name" id="overlay-name"></div>
        <div class="overlay-badges" id="overlay-badges"></div>
        <div class="overlay-stats" id="overlay-stats"></div>
        <div class="overlay-card-text" id="overlay-card-text"></div>
      </div>
    </div>
  </div>"""

    # ── full HTML ─────────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>One Piece TCG — Top Deck Cards by Leader</title>
  <link rel="shortcut icon" type="image/x-icon" href="../favicon.ico">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: system-ui, sans-serif;
      background: #0f0f13;
      color: #e0e0e0;
      min-height: 100vh;
    }}

    /* ── Sidebar ── */
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
      padding: .1rem .8rem .1rem 1.2rem;
      gap: .4rem;
    }}
    .sidebar a {{
      color: #c4c4d4;
      text-decoration: none;
      font-size: .82rem;
      flex: 1;
      padding: .35rem 0;
      line-height: 1.3;
    }}
    .sidebar a:hover {{ color: #a78bfa; }}
    .nav-card-id {{ color: #6b6b8a; font-size: .72rem; }}
    .nav-total {{
      font-size: .72rem;
      color: #6b6b8a;
      white-space: nowrap;
    }}

    /* ── Main ── */
    .main {{
      margin-left: 240px;
      padding: 2rem 2rem 6rem;
    }}

    /* ── Leader section ── */
    .leader-section {{
      margin-bottom: 5rem;
      scroll-margin-top: 1rem;
    }}
    .section-header {{
      position: sticky;
      top: 0;
      z-index: 40;
      background: #0f0f13;
      padding: .6rem 0;
      border-bottom: 2px solid #2a2a3a;
      margin-bottom: 1.8rem;
    }}
    .leader-hero {{
      display: flex;
      align-items: center;
      gap: 1.2rem;
    }}
    .leader-img {{
      width: 64px;
      border-radius: 6px;
      flex-shrink: 0;
      object-fit: cover;
      aspect-ratio: 5/7;
      cursor: pointer;
      transition: transform .15s, box-shadow .15s;
    }}
    .leader-img:hover {{
      transform: translateY(-2px);
      box-shadow: 0 0 0 2px #a78bfa;
    }}
    .leader-meta h2 {{
      font-size: 1.25rem;
      color: #a78bfa;
      line-height: 1.2;
    }}
    .deck-count {{
      font-size: .78rem;
      color: #6b6b8a;
      display: block;
      margin-top: .2rem;
    }}

    /* ── Type sub-section ── */
    .type-section {{ margin-bottom: 2.5rem; }}
    .type-heading {{
      font-size: 1rem;
      color: #c4c4d4;
      margin-bottom: .8rem;
      padding-left: .2rem;
      border-left: 3px solid #a78bfa;
      padding-left: .6rem;
    }}

    /* ── Chart ── */
    .chart-details {{
      margin-bottom: 1rem;
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
      overflow-x: auto;
    }}
    .chart-bars {{
      display: flex;
      align-items: flex-end;
      gap: .6rem;
      height: 160px;
      min-width: max-content;
    }}
    .bar-group {{
      display: flex;
      flex-direction: column;
      align-items: center;
      width: 52px;
      height: 100%;
      cursor: default;
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
      min-height: 4px;
    }}
    .bar-seg {{
      transition: filter .15s;
      cursor: default;
      position: relative;
    }}
    .bar-seg:hover {{ filter: brightness(1.35); }}

    /* Segment tooltip */
    .bar-tooltip {{
      position: fixed;
      background: #1c1c28;
      border: 1px solid #2a2a3a;
      color: #e0e0e0;
      font-size: .72rem;
      padding: .3rem .6rem;
      border-radius: 6px;
      pointer-events: none;
      white-space: nowrap;
      z-index: 300;
      display: none;
    }}
    .bar-tooltip.visible {{ display: block; }}
    .bar-val {{
      font-size: .65rem;
      font-weight: 700;
      color: #c4c4d4;
    }}
    .bar-label {{
      font-size: .58rem;
      color: #6b6b8a;
      margin-top: .3rem;
      text-align: center;
      width: 100%;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }}

    /* ── Cards grid ── */
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
      gap: .85rem;
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
      font-size: .68rem;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      z-index: 1;
    }}
    .card-img {{
      width: 100%;
      aspect-ratio: 5/7;
      object-fit: cover;
      object-position: top;
      background: #111118;
      display: block;
    }}
    .card-body {{
      padding: .55rem .65rem .7rem;
      display: flex;
      flex-direction: column;
      gap: .3rem;
    }}
    .card-name {{
      font-size: .75rem;
      font-weight: 600;
      color: #e0e0e0;
      line-height: 1.3;
    }}
    .card-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: .25rem;
      align-items: center;
    }}
    .badge {{
      background: #2a2a3a;
      color: #a0a0c0;
      font-size: .62rem;
      padding: 1px 5px;
      border-radius: 4px;
    }}
    .avg-badge {{ background: #1e2a3a; color: #60a5fa; }}
    .rarity-badge {{ background: #2e1f4a; color: #c084fc; }}
    .usage-bar-wrap {{
      height: 4px;
      background: #2a2a3a;
      border-radius: 2px;
      overflow: hidden;
      margin-top: .15rem;
    }}
    .usage-bar {{
      height: 100%;
      border-radius: 2px;
      transition: width .3s;
    }}
    .usage-label {{
      font-size: .68rem;
      font-weight: 700;
    }}

    /* ── Overlay ── */
    .overlay-backdrop {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.78);
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
      align-items: flex-start;
    }}
    .overlay-img {{
      width: 300px;
      border-radius: 10px;
      display: block;
    }}
    .overlay-info-col {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: .9rem;
      min-width: 0;
    }}
    .overlay-name {{
      font-size: 1.1rem;
      font-weight: 700;
      color: #fff;
      line-height: 1.3;
    }}
    .overlay-badges {{ display: flex; flex-wrap: wrap; gap: .35rem; }}
    .overlay-stats {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
      gap: .5rem;
    }}
    .overlay-stat {{
      background: #1c1c28;
      border: 1px solid #2a2a3a;
      border-radius: 7px;
      padding: .4rem .65rem;
    }}
    .overlay-stat-label {{
      font-size: .58rem;
      color: #6b6b8a;
      text-transform: uppercase;
      letter-spacing: .05em;
    }}
    .overlay-stat-value {{
      font-size: .95rem;
      font-weight: 700;
      color: #e0e0e0;
    }}
    .overlay-close {{
      position: absolute;
      top: .8rem; right: .9rem;
      background: none;
      border: none;
      color: #6b6b8a;
      font-size: 1.2rem;
      cursor: pointer;
      padding: 2px 7px;
      border-radius: 4px;
    }}
    .overlay-close:hover {{ color: #e0e0e0; background: #2a2a3a; }}
    .overlay-card-text {{
      font-size: .8rem;
      color: #b0b0c8;
      line-height: 1.6;
      border-top: 1px solid #2a2a3a;
      padding-top: .7rem;
      white-space: pre-wrap;
    }}
    .overlay-card-text:empty {{ display: none; }}

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
      .overlay {{ flex-direction: column; }}
      .overlay-img-col {{ flex: none; align-self: center; }}
      .leader-section {{ scroll-margin-top: 52px; }}
      .section-header {{ top: 52px; }}
    }}
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
    <h1>TCG Top Cards<br><small style="color:#6b6b8a;font-weight:400">by Leader</small></h1>
    <ul>
{nav_items}    </ul>
  </nav>

  <main class="main">
{sections}  </main>

{overlay}

  <script>
    // ── Bar segment tooltip ──────────────────────────────────────────────
    const barTooltip = document.getElementById('bar-tooltip');
    document.addEventListener('mouseover', e => {{
      const seg = e.target.closest('.bar-seg');
      if (!seg) return;
      barTooltip.textContent = seg.dataset.tip || '';
      barTooltip.classList.add('visible');
    }});
    document.addEventListener('mouseout', e => {{
      if (!e.target.closest('.bar-seg')) return;
      barTooltip.classList.remove('visible');
    }});
    document.addEventListener('mousemove', e => {{
      if (!barTooltip.classList.contains('visible')) return;
      barTooltip.style.left = (e.clientX + 12) + 'px';
      barTooltip.style.top  = (e.clientY - 28) + 'px';
    }});

    // ── Card / leader click → overlay ────────────────────────────────────
    const backdrop  = document.getElementById('overlay');
    const oImg      = document.getElementById('overlay-img');
    const oName     = document.getElementById('overlay-name');
    const oBadges   = document.getElementById('overlay-badges');
    const oStats    = document.getElementById('overlay-stats');
    const oCardText = document.getElementById('overlay-card-text');

    const RARITY_LABELS = {{
      L:'Leader', C:'Common', UC:'Uncommon', R:'Rare',
      SR:'Super Rare', SEC:'Secret Rare', SP:'Special',
    }};

    function stat(label, value, style='') {{
      if (value === null || value === undefined || value === '') return '';
      return `<div class="overlay-stat">
        <div class="overlay-stat-label">${{label}}</div>
        <div class="overlay-stat-value"${{style ? ` style="${{style}}"` : ''}}>${{value}}</div>
      </div>`;
    }}

    function openOverlay(el) {{
      const d = el.dataset;
      oImg.src = d.image;
      oImg.alt = d.name;
      oName.textContent = d.name;

      // ── Badges: card ID + rarity ──────────────────────────────────────
      const rarityLabel = d.rarity ? (RARITY_LABELS[d.rarity] || d.rarity) : '';
      oBadges.innerHTML =
        `<span class="badge">${{d.id}}</span>` +
        (d.rarity ? `<span class="badge rarity-badge">${{d.rarity}} — ${{rarityLabel}}</span>` : '');

      // ── Usage colour ─────────────────────────────────────────────────
      const usagePct = parseFloat(d.usage);
      const col = usagePct >= 80 ? '#34d399'
                : usagePct >= 50 ? '#a3e635'
                : usagePct >= 25 ? '#fbbf24' : '#f87171';

      // ── Market price formatting ───────────────────────────────────────
      const priceStr = d.marketPrice && d.marketPrice !== ''
        ? `$${{parseFloat(d.marketPrice).toFixed(2)}}` : '';

      // ── Stats grid ───────────────────────────────────────────────────
      oStats.innerHTML =
        stat('Usage',           `${{d.usage}}%`,                col ? `color:${{col}}` : '') +
        stat('Decks with card', `${{d.decks}} / ${{d.total}}`) +
        stat('Avg copies',      parseFloat(d.avg).toFixed(1)) +
        stat('Market price',    priceStr,                       'color:#a78bfa') +
        stat('Color',           d.cardColor) +
        stat('Type',            d.cardType) +
        stat('Power',           d.cardPower) +
        (d.cardCost && d.cardCost !== '' ? stat('Cost', d.cardCost) : '') +
        stat('Counter',         d.counterAmount) +
        stat('Attribute',       d.attribute) +
        stat('Sub-types',       d.subTypes);

      // ── Card text ────────────────────────────────────────────────────
      oCardText.textContent = d.cardText || '';

      backdrop.classList.add('open');
    }}

    document.querySelectorAll('.card, .card-trigger').forEach(el => {{
      el.addEventListener('click', () => openOverlay(el));
      el.addEventListener('keydown', e => {{
        if (e.key === 'Enter' || e.key === ' ') openOverlay(el);
      }});
    }});

    document.getElementById('overlay-close').addEventListener('click', () => {{
      backdrop.classList.remove('open');
    }});
    backdrop.addEventListener('click', e => {{
      if (e.target === backdrop) backdrop.classList.remove('open');
    }});
    document.addEventListener('keydown', e => {{
      if (e.key === 'Escape') backdrop.classList.remove('open');
    }});

    /* ── Hamburger / sidebar ── */
    const hamburger       = document.getElementById('hamburger');
    const sidebar         = document.getElementById('sidebar');
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
</html>
"""


def process_leader(leader_id: str, limit: int | None = None, force: bool = False) -> dict | None:
    """Process one leader and return the result dict, or None if skipped.

    Args:
        leader_id: The leader card ID to process.
        limit: Maximum number of decklists to evaluate. None means no limit.
        force: If True, ignore deck-level cache and re-scrape all decklists.
    """
    cache_file = CACHE_DIR / f"{leader_id}.json"

    print(f"\n{'='*60}")
    print(f"Leader: {leader_id}")
    print(f"{'='*60}")

    print("  Fetching deck URLs...")
    deck_urls = get_deck_urls_for_leader(leader_id)
    print(f"  Found {len(deck_urls)} deck(s)")

    if not deck_urls:
        print("  Skipping – no decklists found.")
        return None

    if limit is not None:
        deck_urls = deck_urls[:limit]
        print(f"  Limited to {len(deck_urls)} deck(s)")

    all_decklists = []
    cached_count = 0
    for i, url in enumerate(deck_urls, 1):
        if not force:
            cached = load_cached_decklist(url)
            if cached is not None:
                all_decklists.append(cached)
                cached_count += 1
                continue

        print(f"  [{i}/{len(deck_urls)}] Scraping {url}")
        try:
            parsed = parse_decklist(url)
            save_cached_decklist(url, parsed)
            all_decklists.append(parsed)
        except Exception as exc:
            print(f"    [error] {exc}")

    new_count = len(all_decklists) - cached_count
    print(f"  {cached_count} deck(s) loaded from cache, {new_count} newly scraped")

    print("  Aggregating stats...")
    stats = aggregate_stats(all_decklists)

    result = {
        "leader_id": leader_id,
        "total_decks": len(all_decklists),
        "card_stats": stats,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  Saved -> {cache_file}")

    # Print a quick summary
    for card_type, cards in stats.items():
        if card_type.lower() == "leader":
            continue
        print(f"\n  --- {card_type} ---")
        for card in cards[:10]:
            print(
                f"    {card['usage_pct']:5.1f}%  x{card['avg_copies_when_played']:.1f}  "
                f"{card['card_name']} ({card['card_id']})"
            )

    # Build a simplified result for HTML generation
    leader_entry = stats.get("Leader", [{}])[0] if stats.get("Leader") else {
        "card_id": leader_id,
        "card_name": leader_id,
        "image_url": card_image_url(leader_id),
        "usage_pct": 100.0,
    }
    non_leader_stats = {k: v for k, v in stats.items() if k.lower() != "leader"}
    return {
        "leader_id": leader_id,
        "leader": leader_entry,
        "total_decks": len(all_decklists),
        "card_stats": non_leader_stats,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fetch top cards for each leader.")
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of decklists to evaluate per leader (default: no limit)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Ignore cached results and re-scrape all leaders",
    )
    args = parser.parse_args()

    leaders: list[str] = json.loads(LEADERS_FILE.read_text())
    print(f"Processing {len(leaders)} leader(s): {', '.join(leaders)}")
    if args.limit is not None:
        print(f"Decklist limit per leader: {args.limit}")
    if args.force:
        print("Force mode: ignoring cache")

    all_results = []
    for leader_id in leaders:
        try:
            result = process_leader(leader_id, limit=args.limit, force=args.force)
            if result:
                all_results.append(result)
        except Exception as exc:
            print(f"[ERROR] Failed processing {leader_id}: {exc}")

    if all_results:
        out_path = Path(__file__).parent / "index.html"
        print(f"\nBuilding HTML -> {out_path}")
        out_path.write_text(build_html(all_results), encoding="utf-8")
        print("HTML written.")

    print("\nDone.")


if __name__ == "__main__":
    main()
