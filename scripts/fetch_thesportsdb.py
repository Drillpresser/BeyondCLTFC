"""Fetch player bio, photos, former teams and honours from TheSportsDB.

TheSportsDB is a free, crowd-sourced JSON API (no scraping, works from any IP).
Coverage/quality varies by player, so we treat it as a *supplement* for cross-
checking bio and for the "former teams" timeline + photos — not as a stats spine.

Pipeline per player:
  1. searchplayers.php?p=NAME -> pick the first Soccer match; cache its idPlayer.
  2. lookupformerteams.php + lookuphonours.php for that id.

Usage:
  python fetch_thesportsdb.py                 # all CLTFC players (asa_players.json)
  python fetch_thesportsdb.py "Ashley Westwood"

Writes:
  data/raw/thesportsdb_ids.json   name -> idPlayer (persistent cache)
  data/raw/thesportsdb.json       name -> {id, bio, former_teams:[...], honours:[...]}
"""
from __future__ import annotations

import json
import sys
import time

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    sys.exit("Missing deps. Run: pip install -r requirements.txt")

session = requests.Session()
session.headers.update({"User-Agent": config.WIKI_USER_AGENT})

# The shared test key ("3") is aggressively rate-limited, so we go slow and back
# off on 429. Set THESPORTSDB_KEY to your own key for faster, more complete runs.
DELAY = 2.0


def polite_get(path: str, *, retries: int = 5, **params):
    delay = DELAY
    for attempt in range(retries):
        time.sleep(delay)
        resp = session.get(f"{config.THESPORTSDB_API}/{path}", params=params, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5 * (attempt + 1)))
            print(f"    429 rate-limited; waiting {wait}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json() or {}
    resp.raise_for_status()
    return resp.json() or {}


def load(fname: str) -> dict:
    p = config.RAW_DIR / fname
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save(fname: str, data) -> None:
    (config.RAW_DIR / fname).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def resolve_id(name: str, cache: dict) -> str | None:
    if name in cache:
        return cache[name]
    print(f"  searching '{name}'...")
    data = polite_get("searchplayers.php", p=name)
    players = data.get("player") or []
    soccer = next((p for p in players if (p.get("strSport") == "Soccer")), None)
    hit = soccer or (players[0] if players else None)
    cache[name] = hit.get("idPlayer") if hit else None
    print(f"    -> {cache[name]}")
    return cache[name]


def bio_from(hit: dict) -> dict:
    """Map the searchplayers record into our bio shape (dropping blanks)."""
    fields = {
        "birth_date": hit.get("dateBorn"),
        "nationality": hit.get("strNationality"),
        "position": hit.get("strPosition"),
        "photo_url": hit.get("strCutout") or hit.get("strThumb"),
        "height": hit.get("strHeight"),
        "weight": hit.get("strWeight"),
        "current_team": hit.get("strTeam"),
    }
    return {k: v for k, v in fields.items() if v}


def former_teams(pid: str) -> list[dict]:
    data = polite_get("lookupformerteams.php", id=pid)
    rows = data.get("formerteams") or []
    out = []
    for r in rows:
        if r.get("strSport") and r["strSport"] != "Soccer":
            continue
        out.append(
            {
                "team": r.get("strFormerTeam"),
                "joined": r.get("strJoined"),
                "departed": r.get("strDeparted"),
            }
        )
    return out


def honours(pid: str) -> list[dict]:
    data = polite_get("lookuphonours.php", id=pid)
    rows = data.get("honours") or []
    return [{"honour": r.get("strHonour"), "season": r.get("strSeason")} for r in rows]


def main() -> None:
    from fetch_wikipedia import player_names_from_asa

    names = sys.argv[1:] or player_names_from_asa()
    print(f"TheSportsDB fetch for {len(names)} player(s).")

    ids = load("thesportsdb_ids.json")
    out = load("thesportsdb.json")

    for name in names:
        if name in out:  # already fetched (or a cached no-match) — resume, don't re-hammer
            continue
        try:
            data = polite_get("searchplayers.php", p=name)
            players = data.get("player") or []
            hit = next((p for p in players if p.get("strSport") == "Soccer"), None) or (
                players[0] if players else None
            )
            pid = hit.get("idPlayer") if hit else None
            ids[name] = pid
            if not pid:
                out[name] = {"id": None, "bio": {}, "former_teams": [], "honours": []}
                print(f"  {name}: no match")
                continue
            out[name] = {
                "id": pid,
                "bio": bio_from(hit),
                "former_teams": former_teams(pid),
                "honours": honours(pid),
            }
            print(f"  {name}: {len(out[name]['former_teams'])} former teams, "
                  f"{len(out[name]['honours'])} honours")
        except Exception as exc:  # noqa: BLE001 - keep going past individual failures
            print(f"    error for '{name}': {exc}")
        finally:
            save("thesportsdb_ids.json", ids)
            save("thesportsdb.json", out)

    print("TheSportsDB fetch complete.")


if __name__ == "__main__":
    main()
