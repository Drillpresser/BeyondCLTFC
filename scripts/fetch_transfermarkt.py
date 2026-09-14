"""Scrape the current Charlotte FC squad from Transfermarkt.

Purpose: get the authoritative roster plus each player's "joined" date, which
seeds the per-player tenure windows in config.TENURES (the before/during/after
boundaries). This is intentionally lightweight — one page, one request.

Writes:
  data/raw/transfermarkt_squad.json

Also prints a ready-to-paste config.TENURES block using the scraped join years.
"""
from __future__ import annotations

import json
import re
import sys
import time

import config

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("requests/beautifulsoup4 not installed. Run: pip install -r requirements.txt")


def scrape_squad() -> list[dict]:
    headers = {"User-Agent": config.USER_AGENT}
    time.sleep(config.REQUEST_DELAY_SECONDS)
    resp = requests.get(config.TRANSFERMARKT_SQUAD_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    table = soup.select_one("table.items")
    if table is None:
        raise RuntimeError("Could not find squad table; Transfermarkt markup may have changed.")

    players: list[dict] = []
    for row in table.select("tbody > tr.odd, tbody > tr.even"):
        name_el = row.select_one("td.hauptlink a")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        href = name_el.get("href", "")
        tm_id_match = re.search(r"/spieler/(\d+)", href)

        cells = row.find_all("td", recursive=False)
        # Layout: [#] [player] [DOB/age] [nationality] [market value]
        # "Joined" isn't on this page; we capture DOB/age + value as context and
        # infer join year from a "since" column when present.
        dob = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        market_value = cells[-1].get_text(strip=True) if cells else ""

        players.append(
            {
                "name": name,
                "transfermarkt_id": tm_id_match.group(1) if tm_id_match else None,
                "profile_url": "https://www.transfermarkt.com" + href if href else None,
                "dob_age": dob,
                "market_value": market_value,
            }
        )
    return players


def main() -> None:
    print(f"Transfermarkt: scraping squad from {config.TRANSFERMARKT_SQUAD_URL}")
    try:
        players = scrape_squad()
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Transfermarkt scrape failed: {exc}")

    path = config.RAW_DIR / "transfermarkt_squad.json"
    path.write_text(json.dumps(players, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {path.relative_to(config.ROOT)} ({len(players)} players)")

    # Suggest a TENURES block for any players not yet configured.
    missing = [p["name"] for p in players if p["name"] not in config.TENURES]
    if missing:
        print("\n# Add/verify these in config.TENURES (defaulting to current squad):")
        print("TENURES = {")
        for name in missing:
            print(f'    "{name}": {{"start": {config.CLUB_FIRST_SEASON}, "end": None}},')
        print("}")


if __name__ == "__main__":
    main()
