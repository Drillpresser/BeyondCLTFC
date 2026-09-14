"""Fetch full cross-league career stats from Transfermarkt.

Transfermarkt has the deepest per-season, per-competition career data of any of
our sources (apps / goals / assists / minutes across every club and league),
which is exactly the before/during/after shape this project needs and covers
pros far better than Wikipedia. Transfermarkt itself is JS-rendered with an
obfuscated internal API, so we don't scrape it directly: we query a self-hosted
`felipeall/transfermarkt-api` instance over HTTP (see README for how to run it).

Point TRANSFERMARKT_API at your running instance (default http://localhost:8000).
If it isn't reachable the fetch is skipped cleanly, so it's safe as a best-effort
CI step.

Pipeline per player:
  1. /players/search/{name} -> first result's id (cached).
  2. /players/{id}/profile  -> bio.
     /players/{id}/stats    -> per-competition/season rows.

Usage:
  python fetch_transfermarkt.py                 # all CLTFC players
  python fetch_transfermarkt.py "Ashley Westwood"

Writes:
  data/raw/transfermarkt_ids.json   name -> player id (persistent cache)
  data/raw/transfermarkt.json       name -> {id, bio, seasons:[...]}
"""
from __future__ import annotations

import json
import re
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
DELAY = 0.3  # querying our own local instance; just avoid hammering it


def api_get(path: str):
    time.sleep(DELAY)
    resp = session.get(f"{config.TRANSFERMARKT_API}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_reachable() -> bool:
    try:
        session.get(f"{config.TRANSFERMARKT_API}/", timeout=5)
        return True
    except requests.RequestException as exc:
        print(f"  Transfermarkt API not reachable at {config.TRANSFERMARKT_API} ({exc}).")
        print("  Skipping — start the felipeall/transfermarkt-api container (see README).")
        return False


def load(fname: str) -> dict:
    p = config.RAW_DIR / fname
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save(fname: str, data) -> None:
    (config.RAW_DIR / fname).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def to_int(val):
    """Transfermarkt numbers arrive as '1.234' / "1'234" / '-'; keep digits only."""
    if val is None:
        return None
    s = re.sub(r"[^\d]", "", str(val))
    return int(s) if s else None


def resolve_id(name: str, cache: dict) -> str | None:
    if name in cache:
        return cache[name]
    print(f"  searching '{name}'...")
    results = api_get(f"/players/search/{requests.utils.quote(name)}").get("results") or []
    cache[name] = str(results[0]["id"]) if results else None
    print(f"    -> {cache[name]}")
    return cache[name]


def parse_profile(profile: dict) -> dict:
    fields = {
        "birth_date": profile.get("dateOfBirth"),
        "nationality": ", ".join(profile.get("citizenship") or [])
        if isinstance(profile.get("citizenship"), list)
        else profile.get("citizenship"),
        "position": (profile.get("position") or {}).get("main")
        if isinstance(profile.get("position"), dict)
        else profile.get("position"),
        "photo_url": profile.get("imageURL"),
        "height": profile.get("height"),
        "foot": profile.get("foot"),
        "current_team": (profile.get("club") or {}).get("name")
        if isinstance(profile.get("club"), dict)
        else profile.get("club"),
    }
    return {k: v for k, v in fields.items() if v}


def parse_stats(stats_payload: dict) -> list[dict]:
    rows = []
    for r in stats_payload.get("stats") or []:
        season = r.get("seasonID")
        try:
            year = int(str(season)[:4])
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "season": year,
                "season_label": str(season),
                "competition": r.get("competitionName"),
                "club": r.get("clubName"),
                "apps": to_int(r.get("appearances")),
                "goals": to_int(r.get("goals")),
                "assists": to_int(r.get("assists")),
                "minutes": to_int(r.get("minutesPlayed")),
                "yellow": to_int(r.get("yellowCards")),
                "red": to_int(r.get("redCards")),
            }
        )
    return rows


def main() -> None:
    from fetch_wikipedia import player_names_from_asa

    names = sys.argv[1:] or player_names_from_asa()
    print(f"Transfermarkt fetch for {len(names)} player(s).")

    if not api_reachable():
        sys.exit(0)  # clean no-op; CI treats missing data as best-effort

    ids = load("transfermarkt_ids.json")
    out = load("transfermarkt.json")

    for name in names:
        try:
            pid = resolve_id(name, ids)
            if not pid:
                out[name] = {"id": None, "bio": {}, "seasons": []}
                continue
            profile = api_get(f"/players/{pid}/profile")
            stats = api_get(f"/players/{pid}/stats")
            out[name] = {
                "id": pid,
                "bio": parse_profile(profile),
                "seasons": parse_stats(stats),
            }
            print(f"    {len(out[name]['seasons'])} season rows")
        except Exception as exc:  # noqa: BLE001 - keep going past individual failures
            print(f"    error for '{name}': {exc}")
        finally:
            save("transfermarkt_ids.json", ids)
            save("transfermarkt.json", out)

    print("Transfermarkt fetch complete.")


if __name__ == "__main__":
    main()
