#!/usr/bin/env python3
"""
Scrapes futbol-libre.su/agenda, decodes the base64 'r' stream URLs,
and generates agenda.html with direct links.

Usage:
    python3 scrape.py
    python3 scrape.py --output my-output.html

Requires:
    pip install requests beautifulsoup4
"""

import argparse
import base64
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run: pip install requests beautifulsoup4")
    sys.exit(1)

AGENDA_URL = "https://futbol-libre.su/agenda"
DEFAULT_OUTPUT = "index.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Fetch & parse
# ---------------------------------------------------------------------------

def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def decode_r_param(href: str) -> str:
    """Base64-decode the 'r' query parameter from a futbol-libres URL."""
    parsed = urllib.parse.urlparse(href)
    params = urllib.parse.parse_qs(parsed.query)
    if "r" in params:
        try:
            return base64.b64decode(params["r"][0]).decode("utf-8")
        except Exception:
            pass
    return href


def _is_bst(now_utc: datetime) -> bool:
    """BST (UTC+1): last Sunday in March 01:00 UTC -> last Sunday in October 01:00 UTC."""
    year = now_utc.year
    # Last Sunday in March
    march_last = datetime(year, 4, 1, 1, 0, tzinfo=timezone.utc) - timedelta(days=1)
    bst_start = march_last - timedelta(days=(march_last.weekday() + 1) % 7)
    # Last Sunday in October
    oct_last = datetime(year, 11, 1, 1, 0, tzinfo=timezone.utc) - timedelta(days=1)
    bst_end = oct_last - timedelta(days=(oct_last.weekday() + 1) % 7)
    return bst_start <= now_utc < bst_end


def _is_pdt(now_utc: datetime) -> bool:
    """PDT (UTC-7): second Sunday in March 02:00 -> first Sunday in November 02:00."""
    year = now_utc.year
    # Second Sunday in March
    march1 = datetime(year, 3, 1, 2, 0, tzinfo=timezone.utc)
    first_sun_march = march1 + timedelta(days=(6 - march1.weekday()) % 7)
    pdt_start = first_sun_march + timedelta(weeks=1)
    # First Sunday in November
    nov1 = datetime(year, 11, 1, 2, 0, tzinfo=timezone.utc)
    pdt_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return pdt_start <= now_utc < pdt_end


def london_to_pacific(time_str: str) -> str:
    """
    Convert a 24-hour London local time string (e.g. '20:00') to Pacific time.
    London is GMT (UTC+0) in winter and BST (UTC+1) in summer.
    Pacific is PST (UTC-8) in winter and PDT (UTC-7) in summer.
    Returns a string like '20:00 BST / 12:00 PDT'.
    """
    try:
        now_utc = datetime.now(timezone.utc)
        year, month, day = now_utc.year, now_utc.month, now_utc.day

        london_offset = 1 if _is_bst(now_utc) else 0
        london_label = "BST" if london_offset else "GMT"

        pacific_offset = -7 if _is_pdt(now_utc) else -8
        pacific_label = "PDT" if pacific_offset == -7 else "PST"

        h, m = map(int, time_str.split(":"))
        # Convert London local -> UTC -> Pacific
        london_dt = datetime(year, month, day, h, m, tzinfo=timezone.utc) - timedelta(hours=london_offset)
        pacific_dt = london_dt + timedelta(hours=pacific_offset)
        pacific_str = pacific_dt.strftime("%H:%M")
        return f"{time_str} {london_label} / {pacific_str} {pacific_label}"
    except Exception:
        return time_str


def parse_agenda(html: str) -> tuple[str, list[dict]]:
    """
    Returns (date_text, games) where each game is:
        {
            "title": str,
            "time":  str,
            "streams": [{"channel": str, "quality": str, "url": str}, ...]
        }
    """
    soup = BeautifulSoup(html, "html.parser")

    # Date banner
    date_div = soup.find("div", class_="sombreada_css3")
    date_text = date_div.get_text(strip=True) if date_div else "Agenda Deportiva"

    games: list[dict] = []

    menu = soup.find("ul", class_="menu")
    if not menu:
        print("Warning: could not find <ul class='menu'> in the page.")
        return date_text, games

    for li in menu.find_all("li", recursive=False):
        if "subitem1" in (li.get("class") or []):
            continue  # skip orphan subitems at top level

        main_a = li.find("a", recursive=False)
        if not main_a:
            continue

        # Pull out the time span before reading the title text
        time_span = main_a.find("span", class_="t")
        time_text = time_span.get_text(strip=True) if time_span else ""
        if time_span:
            time_span.decompose()
        if time_text:
            time_text = london_to_pacific(time_text)

        title = main_a.get_text(strip=True)

        # Nested <ul> holds the stream links
        streams: list[dict] = []
        sub_ul = li.find("ul")
        if sub_ul:
            for sub_li in sub_ul.find_all("li"):
                sub_a = sub_li.find("a")
                if not sub_a:
                    continue

                href = sub_a.get("href", "")
                decoded_url = decode_r_param(href)

                quality_span = sub_a.find("span")
                quality = quality_span.get_text(strip=True) if quality_span else ""
                if quality_span:
                    quality_span.decompose()

                channel = sub_a.get_text(strip=True)
                streams.append({"channel": channel, "quality": quality, "url": decoded_url})

        games.append({"title": title, "time": time_text, "streams": streams})

    return date_text, games


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def build_html(date_text: str, games: list[dict]) -> str:
    game_blocks: list[str] = []
    for game in games:
        stream_items = []
        for s in game["streams"]:
            stream_items.append(
                f'<a class="stream-link" href="{s["url"]}" target="_blank" rel="noopener noreferrer">'
                f'<span class="channel">{s["channel"]}</span>'
                f'<span class="quality">{s["quality"]}</span>'
                f"</a>"
            )
        streams_html = (
            "\n".join(stream_items)
            if stream_items
            else '<p class="no-streams">Sin señales disponibles</p>'
        )

        game_blocks.append(
            f"""
    <div class="game-card">
      <button class="game-header" onclick="toggle(this)">
        <span class="time">{game["time"]}</span>
        <span class="title">{game["title"]}</span>
        <span class="arrow">&#9654;</span>
      </button>
      <div class="streams" hidden>
        {streams_html}
      </div>
    </div>"""
        )

    cards = "\n".join(game_blocks)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Agenda Deportiva</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: Arial, Helvetica, sans-serif;
      background: #f2f3f5;
      color: #1a1a1a;
    }}

    header {{
      background: #0d1b2a;
      color: #fff;
      text-align: center;
      padding: 1rem 1.25rem;
      font-size: 1rem;
      font-weight: 700;
      letter-spacing: 0.03em;
      border-bottom: 3px solid #4caf50;
    }}

    .container {{
      max-width: 680px;
      margin: 1.25rem auto;
      padding: 0 0.75rem 2rem;
    }}

    .game-card {{
      background: #fff;
      border-radius: 8px;
      margin-bottom: 0.6rem;
      box-shadow: 0 1px 4px rgba(0,0,0,.1);
      overflow: hidden;
    }}

    .game-header {{
      width: 100%;
      display: flex;
      align-items: center;
      gap: 0.65rem;
      padding: 0.8rem 1rem;
      border: none;
      background: transparent;
      cursor: pointer;
      text-align: left;
      font-size: 0.9rem;
      transition: background 0.15s;
    }}
    .game-header:hover {{ background: #f0f6ff; }}

    .time {{
      flex-shrink: 0;
      background: #0d1b2a;
      color: #fff;
      padding: 0.18rem 0.5rem;
      border-radius: 4px;
      font-size: 0.78rem;
      font-weight: 700;
      white-space: nowrap;
    }}

    .title {{
      flex: 1;
      font-weight: 600;
    }}

    .arrow {{
      color: #aaa;
      font-size: 0.7rem;
      transition: transform 0.2s;
    }}
    .arrow.open {{ transform: rotate(90deg); }}

    .streams {{
      padding: 0.4rem 0.9rem 0.7rem;
      background: #f9f9fb;
    }}

    .stream-link {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.45rem 0.7rem;
      margin-bottom: 0.35rem;
      background: #fff;
      border: 1px solid #e0e4e8;
      border-radius: 5px;
      text-decoration: none;
      color: #0055cc;
      font-size: 0.84rem;
      transition: background 0.15s, border-color 0.15s;
    }}
    .stream-link:hover {{ background: #e6f0ff; border-color: #0055cc; }}

    .channel {{ font-weight: 600; }}
    .quality {{ font-size: 0.75rem; color: #888; margin-left: 0.5rem; }}

    .no-streams {{ color: #aaa; font-size: 0.82rem; padding: 0.3rem 0; }}
  </style>
</head>
<body>
  <header>{date_text}</header>
  <div class="container">
{cards}
  </div>
  <script>
    function toggle(btn) {{
      var panel = btn.nextElementSibling;
      var arrow = btn.querySelector('.arrow');
      var hidden = panel.hasAttribute('hidden');
      if (hidden) {{
        panel.removeAttribute('hidden');
        arrow.classList.add('open');
      }} else {{
        panel.setAttribute('hidden', '');
        arrow.classList.remove('open');
      }}
    }}
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate futbol-libre agenda HTML.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output HTML file path")
    args = parser.parse_args()

    print(f"Fetching {AGENDA_URL} ...")
    raw_html = fetch_html(AGENDA_URL)

    print("Parsing games and decoding stream URLs ...")
    date_text, games = parse_agenda(raw_html)
    print(f"  Found {len(games)} game(s)")

    total_streams = sum(len(g["streams"]) for g in games)
    print(f"  Found {total_streams} stream link(s)")

    output_html = build_html(date_text, games)

    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(output_html)

    print(f"Saved → {args.output}")


if __name__ == "__main__":
    main()
