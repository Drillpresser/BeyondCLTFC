"""Scrape full cross-league career histories from FBref player pages.

ASA only covers MLS/USL/NWSL, so a player's pre- and post-CLTFC seasons in
Europe, Liga MX, etc. are invisible to it. FBref lists *every* season at *every*
club on each player's page — that's the "before"/"after" context this project
needs.

Pipeline per player:
  1. Resolve the FBref player URL from their name via FBref's search endpoint
     (cached in data/raw/fbref_player_ids.json so we only search once).
  2. Fetch the player page and parse the "Standard Stats" table into one row
     per (season, club, competition).

FBref rate-limits hard (429s on bursts; ~1 req/3s is the safe ceiling). Every
request is throttled and 429s back off. Results cache to disk so re-runs are cheap.

Usage:
  python fetch_fbref.py                 # all CLTFC players (from asa_players.json)
  python fetch_fbref.py "Ashley Westwood" "Christian Fuchs"   # just these (testing)

Writes:
  data/raw/fbref_player_ids.json   name -> {id, slug, url}  (persistent cache)
  data/raw/fbref_careers.json      name -> [season rows]
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from urllib.parse import quote

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import pandas as pd
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing deps. Run: pip install -r requirements.txt")

# FBref sits behind Cloudflare, which 403s plain `requests`. curl_cffi
# impersonates a real browser's TLS/JA3 fingerprint and gets through when the
# IP isn't rate-flagged. Fall back to requests so the module still imports.
try:
    from curl_cffi import requests as _http

    def _session():
        return _http.Session(impersonate="chrome")

    _IMPERSONATE = True
except ImportError:
    import requests as _http

    def _session():
        return _http.Session()

    _IMPERSONATE = False

BASE = "https://fbref.com"
SEARCH_URL = BASE + "/search/search.fcgi?hint=&search={q}"
PLAYER_RE = re.compile(r"/en/players/([0-9a-f]{8})/([^/?#]+)")
SEASON_RE = re.compile(r"^\d{4}(-\d{2,4})?$")

# Columns we keep from the (flattened) FBref standard-stats table.
# FBref uses a two-level header; after flattening we match on suffixes.
# Only raw counting stats — FBref's modeled Expected_* columns (xG/npxG/xAG)
# are intentionally not collected.
KEEP = {
    "Season": "season",
    "Age": "age",
    "Squad": "squad",
    "Country": "country",
    "Comp": "comp",
    "LgRank": "lg_rank",
    "Playing Time_MP": "mp",
    "Playing Time_Starts": "starts",
    "Playing Time_Min": "minutes",
    "Performance_Gls": "goals",
    "Performance_Ast": "assists",
    "Performance_G+A": "goals_assists",
    "Performance_PK": "pens",
    "Performance_CrdY": "yellow",
    "Performance_CrdR": "red",
}

session = _session()
session.headers.update(
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BASE + "/",
    }
)


def polite_get(url: str, *, retries: int = 3):
    """GET with a fixed inter-request delay, 429 backoff, and a clear message
    when Cloudflare blocks us (403)."""
    delay = config.REQUEST_DELAY_SECONDS
    for attempt in range(retries):
        time.sleep(delay)
        resp = session.get(url, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", delay * (2 ** (attempt + 1))))
            print(f"    429 rate-limited; waiting {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code == 403:
            raise RuntimeError(
                "403 Cloudflare block"
                + ("" if _IMPERSONATE else " (install curl_cffi for TLS impersonation)")
                + " — FBref is throttling this IP. Retry later or from a residential IP."
            )
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"Gave up after {retries} retries (rate limited): {url}")


def resolve_player(name: str, cache: dict) -> dict | None:
    """Find a player's FBref page. Returns {id, slug, url} or None."""
    if name in cache:
        return cache[name]

    print(f"  resolving '{name}'...")
    resp = polite_get(SEARCH_URL.format(q=quote(name)))

    # A unique match redirects straight to the player page.
    m = PLAYER_RE.search(resp.url)
    if not m:
        # Otherwise parse the search-results page for the first player hit.
        soup = BeautifulSoup(resp.text, "lxml")
        link = soup.select_one('div.search-item-name a[href*="/en/players/"]')
        if link:
            m = PLAYER_RE.search(link.get("href", ""))

    if not m:
        print(f"    no FBref match for '{name}'")
        cache[name] = None
        return None

    pid, slug = m.group(1), m.group(2)
    result = {"id": pid, "slug": slug, "url": f"{BASE}/en/players/{pid}/{slug}"}
    cache[name] = result
    print(f"    -> {result['url']}")
    return result


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join(str(c) for c in col if c and not str(c).startswith("Unnamed"))
            for col in df.columns
        ]
    else:
        df.columns = [str(c) for c in df.columns]
    return df


def find_standard_table(html: str) -> pd.DataFrame | None:
    """FBref buries many tables in HTML comments; uncomment, then pick the
    standard-stats table (has Season + Squad + Comp columns)."""
    html = html.replace("<!--", "").replace("-->", "")
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return None

    best = None
    for raw in tables:
        df = flatten_columns(raw.copy())
        cols = set(df.columns)
        if {"Season", "Squad", "Comp"}.issubset(cols):
            # Prefer the widest such table (the domestic-league career table).
            if best is None or df.shape[1] > best.shape[1]:
                best = df
    return best


def parse_career(html: str) -> list[dict]:
    df = find_standard_table(html)
    if df is None:
        return []

    present = {src: dst for src, dst in KEEP.items() if src in df.columns}
    slim = df[list(present)].rename(columns=present)

    rows = []
    for _, r in slim.iterrows():
        season = str(r.get("season", "")).strip()
        if not SEASON_RE.match(season):  # skip totals / "N Seasons" rows
            continue
        row = {}
        for dst in present.values():
            val = r.get(dst)
            if pd.isna(val):
                val = None
            elif dst not in ("season", "squad", "country", "comp", "lg_rank"):
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    pass
            row[dst] = val
        rows.append(row)
    return rows


def load_cache(fname: str) -> dict:
    path = config.RAW_DIR / fname
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save(fname: str, data) -> None:
    path = config.RAW_DIR / fname
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def player_names_from_asa() -> list[str]:
    path = config.RAW_DIR / "asa_players.json"
    if not path.exists():
        sys.exit("Run fetch_asa.py first (need data/raw/asa_players.json).")
    rows = json.loads(path.read_text(encoding="utf-8"))
    return sorted(r["player_name"] for r in rows if r.get("player_name"))


def main() -> None:
    names = sys.argv[1:] or player_names_from_asa()
    print(f"FBref career scrape for {len(names)} player(s).")

    id_cache = load_cache("fbref_player_ids.json")
    careers = load_cache("fbref_careers.json")

    for name in names:
        try:
            player = resolve_player(name, id_cache)
            if player is None:
                continue
            resp = polite_get(player["url"])
            rows = parse_career(resp.text)
            careers[name] = rows
            print(f"    {len(rows)} season rows")
        except Exception as exc:  # noqa: BLE001 - keep going past individual failures
            print(f"    error for '{name}': {exc}")
        finally:
            # Persist after every player so a crash/ban never loses progress.
            save("fbref_player_ids.json", id_cache)
            save("fbref_careers.json", careers)

    print("FBref career scrape complete.")


if __name__ == "__main__":
    main()
