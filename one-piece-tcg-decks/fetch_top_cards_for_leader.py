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
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://onepiece.limitlesstcg.com"
CDN_BASE = "https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/one-piece"
CACHE_DIR = Path(__file__).parent / "cache"
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

    return output


def process_leader(leader_id: str) -> None:
    cache_file = CACHE_DIR / f"{leader_id}.json"

    print(f"\n{'='*60}")
    print(f"Leader: {leader_id}")
    print(f"{'='*60}")

    print("  Fetching deck URLs...")
    deck_urls = get_deck_urls_for_leader(leader_id)
    print(f"  Found {len(deck_urls)} deck(s)")

    if not deck_urls:
        print("  Skipping – no decklists found.")
        return

    all_decklists = []
    for i, url in enumerate(deck_urls, 1):
        print(f"  [{i}/{len(deck_urls)}] Parsing {url}")
        try:
            parsed = parse_decklist(url)
            all_decklists.append(parsed)
        except Exception as exc:
            print(f"    [error] {exc}")

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
           data-total="{total_decks}">
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
            # usage bar chart: top-15 cards by usage_pct
            chart_cards = cards[:15]
            max_pct = max((c["usage_pct"] for c in chart_cards), default=1)

            bar_items = ""
            for c in chart_cards:
                bar_h = max(4, round(c["usage_pct"] / max_pct * 120))
                colour = pct_color(c["usage_pct"])
                short_name = c["card_name"][:14] + "…" if len(c["card_name"]) > 15 else c["card_name"]
                bar_items += f"""
              <div class="bar-group" title="{html_module.escape(c['card_name'])} ({c['card_id']}) — {c['usage_pct']}%">
                <div class="bar-wrap">
                  <span class="bar-val">{c['usage_pct']}%</span>
                  <div class="bar" style="height:{bar_h}px;background:{colour};"></div>
                </div>
                <div class="bar-label">{html_module.escape(short_name)}</div>
              </div>"""

            # Card grid
            card_items = ""
            for rank, c in enumerate(cards, 1):
                colour = pct_color(c["usage_pct"])
                # Pill: x copies avg
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
        <summary class="chart-toggle">Usage chart (top {len(chart_cards)})</summary>
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
      transition: opacity .15s;
    }}
    .bar-group:hover .bar {{ opacity: .75; }}
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
      max-width: 680px;
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

    @media (max-width: 640px) {{
      .sidebar {{ display: none; }}
      .main {{ margin-left: 0; padding: 1rem; }}
      .overlay {{ flex-direction: column; }}
      .overlay-img-col {{ flex: none; align-self: center; }}
    }}
  </style>
</head>
<body>

  <nav class="sidebar">
    <h1>TCG Top Cards<br><small style="color:#6b6b8a;font-weight:400">by Leader</small></h1>
    <ul>
{nav_items}    </ul>
  </nav>

  <main class="main">
{sections}  </main>

{overlay}

  <script>
    // ── Card / leader click → overlay ────────────────────────────────────
    const backdrop = document.getElementById('overlay');
    const oImg     = document.getElementById('overlay-img');
    const oName    = document.getElementById('overlay-name');
    const oBadges  = document.getElementById('overlay-badges');
    const oStats   = document.getElementById('overlay-stats');

    function openOverlay(el) {{
      const d = el.dataset;
      oImg.src     = d.image;
      oImg.alt     = d.name;
      oName.textContent = d.name;

      oBadges.innerHTML =
        `<span class="badge">${{d.id}}</span>`;

      const usagePct  = parseFloat(d.usage);
      const col = usagePct >= 80 ? '#34d399'
                : usagePct >= 50 ? '#a3e635'
                : usagePct >= 25 ? '#fbbf24' : '#f87171';

      oStats.innerHTML = `
        <div class="overlay-stat">
          <div class="overlay-stat-label">Usage</div>
          <div class="overlay-stat-value" style="color:${{col}}">${{d.usage}}%</div>
        </div>
        <div class="overlay-stat">
          <div class="overlay-stat-label">Decks with card</div>
          <div class="overlay-stat-value">${{d.decks}} / ${{d.total}}</div>
        </div>
        <div class="overlay-stat">
          <div class="overlay-stat-label">Avg copies</div>
          <div class="overlay-stat-value">${{parseFloat(d.avg).toFixed(1)}}</div>
        </div>`;

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
  </script>
</body>
</html>
"""


def process_leader(leader_id: str) -> dict | None:
    """Process one leader and return the result dict, or None if skipped."""
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

    all_decklists = []
    for i, url in enumerate(deck_urls, 1):
        print(f"  [{i}/{len(deck_urls)}] Parsing {url}")
        try:
            parsed = parse_decklist(url)
            all_decklists.append(parsed)
        except Exception as exc:
            print(f"    [error] {exc}")

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
    leaders: list[str] = json.loads(LEADERS_FILE.read_text())
    print(f"Processing {len(leaders)} leader(s): {', '.join(leaders)}")

    all_results = []
    for leader_id in leaders:
        try:
            result = process_leader(leader_id)
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
