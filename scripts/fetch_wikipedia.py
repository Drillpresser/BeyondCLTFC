"""Scrape cross-league career stats from Wikipedia "Career statistics" tables.

Wikipedia is our before/after context source: server-rendered, ToS-clean (CC
BY-SA + public MediaWiki API), no anti-bot layer, and it carries per-season
club/league/appearances/goals across a player's whole career — including the
European/Liga MX seasons that ASA (MLS-only) can't see.

Pipeline per player:
  1. Resolve the Wikipedia page title via the MediaWiki search API (handles
     disambiguation like "(footballer, born 1990)"). Cached to disk.
  2. Fetch the article and parse the club career-stats table into one row per
     (season, club, competition).

Usage:
  python fetch_wikipedia.py                       # all CLTFC players (asa_players.json)
  python fetch_wikipedia.py "Ashley Westwood"     # just these (testing)

Writes:
  data/raw/wikipedia_titles.json    name -> resolved page title (persistent cache)
  data/raw/wikipedia_careers.json   name -> [season rows]
"""
from __future__ import annotations

import io
import json
import re
import sys
import time

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import pandas as pd
    from curl_cffi import requests as _http

    def _session():
        return _http.Session(impersonate="chrome")
except ImportError:
    try:
        import pandas as pd
        import requests as _http

        def _session():
            return _http.Session()
    except ImportError:
        sys.exit("Missing deps. Run: pip install -r requirements.txt")

YEAR_RE = re.compile(r"(\d{4})")
FOOTNOTE_RE = re.compile(r"\[[^\]]*\]")

session = _session()
session.headers.update({"User-Agent": config.WIKI_USER_AGENT})


def polite_get(url: str, **kwargs):
    time.sleep(config.WIKI_DELAY_SECONDS)
    resp = session.get(url, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp


def resolve_title(name: str, cache: dict) -> str | None:
    """Find the Wikipedia article title for a player via the search API."""
    if name in cache:
        return cache[name]
    print(f"  resolving '{name}'...")
    resp = polite_get(
        config.WIKI_API,
        params={
            "action": "query",
            "list": "search",
            "srsearch": f"{name} footballer soccer",
            "srlimit": 1,
            "format": "json",
            "formatversion": 2,
        },
    )
    hits = resp.json().get("query", {}).get("search", [])
    title = hits[0]["title"] if hits else None
    cache[name] = title
    print(f"    -> {title}")
    return title


def flatten_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for col in df.columns:
        parts = col if isinstance(col, tuple) else (col,)
        seen, out = set(), []
        for p in parts:
            p = str(p).strip()
            if p and not p.startswith("Unnamed") and p not in seen:
                seen.add(p)
                out.append(p)
        cols.append(" ".join(out))
    return cols


def to_int(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = FOOTNOTE_RE.sub("", str(val)).strip()
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None


def find_career_table(html: str) -> pd.DataFrame | None:
    """Pick the club career-stats table: has Club + Season + League Apps/Goals."""
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return None
    for raw in tables:
        df = raw.copy()
        df.columns = flatten_columns(df)
        joined = " ".join(df.columns).lower()
        if "club" in joined and "season" in joined and "league apps" in joined:
            return df
    return None


def parse_career(html: str) -> list[dict]:
    df = find_career_table(html)
    if df is None:
        return []

    def col(pred):
        return next((c for c in df.columns if pred(c)), None)

    club_c = col(lambda c: c == "Club") or col(lambda c: c.endswith("Club"))
    season_c = col(lambda c: c == "Season") or col(lambda c: c.endswith("Season"))
    div_c = col(lambda c: c.endswith("Division"))
    la_c = col(lambda c: c == "League Apps")
    lg_c = col(lambda c: c == "League Goals")
    ta_c = col(lambda c: c == "Total Apps")
    tg_c = col(lambda c: c == "Total Goals")
    if not (club_c and season_c and la_c):
        return []

    # Wikipedia uses rowspans for the club column -> NaN on continuation rows.
    df[club_c] = df[club_c].ffill()

    rows = []
    for _, r in df.iterrows():
        season = FOOTNOTE_RE.sub("", str(r.get(season_c, ""))).strip()
        club = str(r.get(club_c, "")).strip()
        # skip subtotal / career-total rows
        if not season or season.lower().startswith("total") or "career" in season.lower():
            continue
        if club.lower() in ("total", "career total"):
            continue
        m = YEAR_RE.search(season)
        if not m:
            continue
        rows.append(
            {
                "season": season,
                "year": int(m.group(1)),
                "club": club,
                "division": str(r.get(div_c, "")).strip() if div_c else "",
                "league_apps": to_int(r.get(la_c)),
                "league_goals": to_int(r.get(lg_c)),
                "total_apps": to_int(r.get(ta_c)) if ta_c else None,
                "total_goals": to_int(r.get(tg_c)) if tg_c else None,
            }
        )
    return rows


def load_cache(fname: str) -> dict:
    path = config.RAW_DIR / fname
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(fname: str, data) -> None:
    (config.RAW_DIR / fname).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def player_names_from_asa() -> list[str]:
    path = config.RAW_DIR / "asa_players.json"
    if not path.exists():
        sys.exit("Run fetch_asa.py first (need data/raw/asa_players.json).")
    rows = json.loads(path.read_text(encoding="utf-8"))
    return sorted(r["player_name"] for r in rows if r.get("player_name"))


def main() -> None:
    names = sys.argv[1:] or player_names_from_asa()
    print(f"Wikipedia career scrape for {len(names)} player(s).")

    titles = load_cache("wikipedia_titles.json")
    careers = load_cache("wikipedia_careers.json")

    for name in names:
        try:
            title = resolve_title(name, titles)
            if not title:
                careers[name] = []
                continue
            resp = polite_get(config.WIKI_PAGE + title.replace(" ", "_"))
            rows = parse_career(resp.text)
            careers[name] = rows
            print(f"    {len(rows)} season rows")
        except Exception as exc:  # noqa: BLE001
            print(f"    error for '{name}': {exc}")
        finally:
            save("wikipedia_titles.json", titles)
            save("wikipedia_careers.json", careers)

    print("Wikipedia career scrape complete.")


if __name__ == "__main__":
    main()
