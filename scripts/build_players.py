"""Merge raw source pulls into the single site-facing dataset: data/players.json.

Joins ASA expected-goals and goals-added on (player_id, season, team_id), tags
every season with its before/during/after phase relative to the player's CLTFC
tenure, and attaches human-readable names. FBref career rows can be layered in
later via the same player/season keys.
"""
from __future__ import annotations

import json
from collections import defaultdict

import config


def load(name: str):
    path = config.RAW_DIR / name
    if not path.exists():
        print(f"  (missing {name}, skipping)")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def index_by_id(rows: list[dict], key: str, value_key: str) -> dict[str, str]:
    return {str(r[key]): r.get(value_key) for r in rows if r.get(key) is not None}


def season_int(row: dict) -> int | None:
    raw = row.get("season_name") or row.get("season")
    try:
        return int(str(raw)[:4])
    except (TypeError, ValueError):
        return None


def tenure_for(name: str | None) -> dict:
    if name and name in config.TENURES:
        return config.TENURES[name]
    # Default: assume they've been at CLTFC since the club's first season.
    return {"start": config.CLUB_FIRST_SEASON, "end": None}


def fbref_season_rows(name: str, careers: dict, tenure: dict) -> list[dict]:
    """Turn a player's FBref career into non-MLS season rows for before/after
    context. MLS is skipped — ASA already covers it with richer metrics."""
    rows = []
    for r in careers.get(name, []) or []:
        comp = str(r.get("comp") or "")
        if "Major League Soccer" in comp:
            continue
        try:
            year = int(str(r.get("season"))[:4])
        except (TypeError, ValueError):
            continue
        stats = {k: r.get(k) for k in ("mp", "starts", "minutes", "goals", "assists", "xg", "npxg", "xag") if k in r}
        rows.append(
            {
                "season": year,
                "season_label": r.get("season"),
                "team": r.get("squad"),
                "league": comp,
                "source": "fbref",
                "phase": config.phase_for(year, tenure["start"], tenure["end"]),
                "fbref": stats,
            }
        )
    return rows


def wiki_season_rows(name: str, careers: dict, tenure: dict) -> list[dict]:
    """Turn a player's Wikipedia career into non-MLS season rows. MLS/Charlotte
    rows are skipped — ASA covers those with richer metrics."""
    rows = []
    for r in careers.get(name, []) or []:
        club = str(r.get("club") or "")
        division = str(r.get("division") or "")
        if "Charlotte" in club or "Major League Soccer" in division:
            continue
        year = r.get("year")
        if year is None:
            continue
        rows.append(
            {
                "season": year,
                "season_label": r.get("season"),
                "team": club,
                "league": division,
                "source": "wikipedia",
                "phase": config.phase_for(year, tenure["start"], tenure["end"]),
                "wikipedia": {
                    "apps": r.get("league_apps"),
                    "goals": r.get("league_goals"),
                    "total_apps": r.get("total_apps"),
                    "total_goals": r.get("total_goals"),
                },
            }
        )
    return rows


def main() -> None:
    print("Building data/players.json ...")
    team_names = index_by_id(load("asa_teams.json"), "team_id", "team_name")
    player_names = index_by_id(load("asa_players.json"), "player_id", "player_name")
    xgoals = load("asa_player_xgoals.json")
    goals_added = load("asa_player_goals_added.json")
    fbref_careers = {}
    fbref_path = config.RAW_DIR / "fbref_careers.json"
    if fbref_path.exists():
        fbref_careers = json.loads(fbref_path.read_text(encoding="utf-8"))
    wiki_careers = {}
    wiki_path = config.RAW_DIR / "wikipedia_careers.json"
    if wiki_path.exists():
        wiki_careers = json.loads(wiki_path.read_text(encoding="utf-8"))

    # (player_id, season, team_id) -> merged season row
    merged: dict[tuple, dict] = {}

    def slot(row: dict) -> dict | None:
        pid = str(row.get("player_id")) if row.get("player_id") is not None else None
        season = season_int(row)
        team_id = str(row.get("team_id")) if row.get("team_id") is not None else None
        if pid is None or season is None:
            return None
        key = (pid, season, team_id)
        if key not in merged:
            merged[key] = {
                "season": season,
                "team_id": team_id,
                "team": team_names.get(team_id, team_id),
                "league": "MLS",
                "source": "asa",
            }
        return merged[key]

    for row in xgoals:
        s = slot(row)
        if s is not None:
            s["xgoals"] = {k: v for k, v in row.items() if k not in ("player_id", "season_name", "team_id")}

    for row in goals_added:
        s = slot(row)
        if s is not None:
            s["goals_added"] = {k: v for k, v in row.items() if k not in ("player_id", "season_name", "team_id")}

    # Group season rows by player.
    by_player: dict[str, list] = defaultdict(list)
    for (pid, season, team_id), season_row in merged.items():
        by_player[pid].append((season, season_row))

    players = []
    for pid, rows in by_player.items():
        name = player_names.get(pid, pid)
        tenure = tenure_for(name)
        seasons = []
        for season, season_row in rows:
            season_row = dict(season_row)
            season_row["phase"] = config.phase_for(season, tenure["start"], tenure["end"])
            seasons.append(season_row)
        # Layer in non-MLS career context (when available).
        seasons.extend(fbref_season_rows(name, fbref_careers, tenure))
        seasons.extend(wiki_season_rows(name, wiki_careers, tenure))
        # Total ordering so output is byte-stable across runs.
        seasons.sort(
            key=lambda s: (
                s["season"],
                s.get("source", ""),
                str(s.get("team") or ""),
                str(s.get("league") or ""),
                str(s.get("season_label") or ""),
            )
        )
        players.append(
            {
                "player_id": f"asa:{pid}",
                "asa_id": pid,
                "name": name,
                "tenure": tenure,
                "seasons": seasons,
            }
        )

    players.sort(key=lambda p: (p["name"] or "", p["asa_id"]))
    out = {
        "club": config.CLUB_NAME,
        "sources": ["asa", "wikipedia", "fbref"],
        "player_count": len(players),
        "players": players,
    }
    path = config.DATA_DIR / "players.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {path.relative_to(config.ROOT)} ({len(players)} players)")


if __name__ == "__main__":
    main()
