"""Fetch per-season player stats from API-FOOTBALL (api-sports.io).

A *sanctioned* REST API (no scraping, works from any IP) covering MLS, Liga MX and
the European leagues. We use it as a cross-check backstop for apps/goals/assists/
minutes by season and league.

Two important free-tier realities:
  * 100 requests/day. Each (player, season) is one request, so this fetch is
    incremental — it only queries (player, season) pairs it hasn't cached yet and
    stops early when the daily quota is hit, resuming on the next run.
  * The free plan restricts which *seasons* you can query. Set APIFOOTBALL_SEASONS
    (comma-separated years) to control the window; it defaults to the CLTFC era.

Skipped entirely when APIFOOTBALL_KEY is unset.

Writes:
  data/raw/apifootball_ids.json   name -> player id (persistent cache)
  data/raw/apifootball.json       name -> {id, seasons:[...]}
"""
from __future__ import annotations

import json
import os
import sys
import time

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    sys.exit("Missing deps. Run: pip install -r requirements.txt")

SEASONS = [
    s.strip() for s in os.environ.get("APIFOOTBALL_SEASONS", ",".join(config.SEASONS)).split(",")
    if s.strip()
]
DELAY = 1.0

session = requests.Session()
session.headers.update({"x-apisports-key": config.APIFOOTBALL_KEY})


class QuotaReached(Exception):
    """Raised when API-FOOTBALL reports the daily request limit is exhausted."""


def api_get(path: str, **params) -> dict:
    time.sleep(DELAY)
    resp = session.get(f"{config.APIFOOTBALL_API}{path}", params=params, timeout=30)
    if resp.status_code == 429:
        raise QuotaReached("HTTP 429")
    resp.raise_for_status()
    body = resp.json()
    errors = body.get("errors")
    # API-FOOTBALL returns 200 with an errors object for quota/plan problems.
    if errors and (isinstance(errors, dict) and any("limit" in str(v).lower() for v in errors.values())):
        raise QuotaReached(str(errors))
    if errors:
        print(f"    api warning: {errors}")
    return body


def load(fname: str) -> dict:
    p = config.RAW_DIR / fname
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save(fname: str, data) -> None:
    (config.RAW_DIR / fname).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def resolve_id(name: str, cache: dict) -> int | None:
    if name in cache:
        return cache[name]
    surname = name.split()[-1]
    print(f"  searching '{name}' (as '{surname}')...")
    body = api_get("/players/profiles", search=surname)
    # Prefer an exact full-name match; else take the first profile.
    best = None
    for row in body.get("response") or []:
        p = row.get("player", {})
        full = f"{p.get('firstname','')} {p.get('lastname','')}".strip().lower()
        if full == name.lower():
            best = p
            break
        best = best or p
    cache[name] = best.get("id") if best else None
    print(f"    -> {cache[name]}")
    return cache[name]


def season_rows(pid: int, season: str) -> list[dict]:
    body = api_get("/players", id=pid, season=season)
    rows = []
    for entry in body.get("response") or []:
        for st in entry.get("statistics") or []:
            games = st.get("games") or {}
            goals = st.get("goals") or {}
            rows.append(
                {
                    "season": int(season),
                    "team": (st.get("team") or {}).get("name"),
                    "league": (st.get("league") or {}).get("name"),
                    "country": (st.get("league") or {}).get("country"),
                    "apps": games.get("appearences"),
                    "minutes": games.get("minutes"),
                    "goals": goals.get("total"),
                    "assists": goals.get("assists"),
                }
            )
    return rows


def main() -> None:
    from fetch_wikipedia import player_names_from_asa

    if not config.APIFOOTBALL_KEY:
        print("APIFOOTBALL_KEY not set — skipping API-FOOTBALL fetch.")
        sys.exit(0)

    names = sys.argv[1:] or player_names_from_asa()
    print(f"API-FOOTBALL fetch for {len(names)} player(s), seasons {SEASONS}.")

    ids = load("apifootball_ids.json")
    out = load("apifootball.json")

    try:
        for name in names:
            pid = resolve_id(name, ids)
            save("apifootball_ids.json", ids)
            if not pid:
                out.setdefault(name, {"id": None, "seasons": []})
                continue
            rec = out.setdefault(name, {"id": pid, "seasons": []})
            rec["id"] = pid
            have = {r["season"] for r in rec["seasons"]}
            for season in SEASONS:
                if int(season) in have:
                    continue  # already cached this (player, season)
                rec["seasons"].extend(season_rows(pid, season))
                save("apifootball.json", out)
            print(f"    {len(rec['seasons'])} season rows total")
    except QuotaReached as q:
        print(f"  Daily quota reached ({q}); progress saved, will resume next run.")

    save("apifootball.json", out)
    print("API-FOOTBALL fetch complete.")


if __name__ == "__main__":
    main()
