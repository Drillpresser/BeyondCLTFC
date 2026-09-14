"""Merge raw source pulls into the single site-facing dataset: data/players.json.

Reads ASA per-season counting stats on (player_id, season, team_id), tags every
season with its before/during/after phase relative to the player's CLTFC tenure,
and attaches human-readable names. FBref career rows can be layered in later via
the same player/season keys. Only raw counting stats are carried through — all
modeled/predictive metrics (xG and the x-family, goals-added) are dropped upstream.
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
        stats = {k: r.get(k) for k in ("mp", "starts", "minutes", "goals", "assists") if k in r}
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


SEASON_SORT_KEY = lambda s: (  # noqa: E731 - small stable-ordering helper
    s["season"],
    s.get("source", ""),
    str(s.get("team") or ""),
    str(s.get("league") or ""),
    str(s.get("season_label") or ""),
)

# Canonical, source-agnostic metric names the wizard edits / adds.
METRIC_KEYS = ("goals", "assists", "apps", "minutes")


def load_overrides() -> dict:
    """Manual edits from the wizard (data/overrides.json). Absent = no-op."""
    path = config.DATA_DIR / "overrides.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_metrics(d: dict) -> dict:
    return {k: d[k] for k in METRIC_KEYS if k in d and d[k] not in (None, "")}


def _tag_phases(player: dict) -> None:
    t = player["tenure"]
    for s in player["seasons"]:
        s["phase"] = config.phase_for(s["season"], t["start"], t["end"])


def apply_overrides(players: list[dict], overrides: dict) -> list[dict]:
    """Layer manual edits on top of fetched data. Overrides never mutate source
    stat buckets — corrected values go in a season's `override` bucket that the
    UI prefers, so the original stays visible in git and the app."""
    by_id = {p["player_id"]: p for p in players}

    for pid, ov in (overrides.get("players") or {}).items():
        p = by_id.get(pid)
        if p is None:
            continue
        if ov.get("bio"):
            p["bio"] = {**p.get("bio", {}), **{k: v for k, v in ov["bio"].items() if v not in (None, "")}}
        if ov.get("tenure"):
            t = ov["tenure"]
            p["tenure"] = {
                "start": t.get("start", p["tenure"]["start"]),
                "end": t.get("end", p["tenure"]["end"]),
            }
            _tag_phases(p)  # tenure drives before/during/after
        # Correct existing seasons: patch matches by season (+ optional source/team).
        for so in ov.get("season_overrides") or []:
            for s in p["seasons"]:
                if (
                    s["season"] == so.get("season")
                    and so.get("source", s.get("source")) == s.get("source")
                    and so.get("team", s.get("team")) == s.get("team")
                ):
                    s["override"] = {**s.get("override", {}), **_clean_metrics(so.get("patch") or {})}
        # Manually added seasons the sources don't have.
        for add in ov.get("added_seasons") or []:
            if add.get("season") is None:
                continue
            row = {
                "season": int(add["season"]),
                "team": add.get("team"),
                "league": add.get("league"),
                "source": "manual",
                "override": _clean_metrics(add),
            }
            row["phase"] = config.phase_for(row["season"], p["tenure"]["start"], p["tenure"]["end"])
            p["seasons"].append(row)
        p["edited"] = True

    # Wholly manual players not present in any source.
    for ap in overrides.get("added_players") or []:
        tenure = ap.get("tenure") or {"start": config.CLUB_FIRST_SEASON, "end": None}
        seasons = []
        for add in ap.get("seasons") or []:
            if add.get("season") is None:
                continue
            row = {
                "season": int(add["season"]),
                "team": add.get("team"),
                "league": add.get("league"),
                "source": "manual",
                "override": _clean_metrics(add),
            }
            row["phase"] = config.phase_for(row["season"], tenure["start"], tenure["end"])
            seasons.append(row)
        players.append(
            {
                "player_id": ap["player_id"],
                "asa_id": None,
                "name": ap.get("name") or ap["player_id"],
                "tenure": tenure,
                "bio": ap.get("bio", {}),
                "seasons": seasons,
                "manual": True,
            }
        )
    return players


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


def tm_season_rows(name: str, tm: dict, tenure: dict) -> list[dict]:
    """Transfermarkt per-competition/season rows (kept for all leagues, incl. MLS,
    so its numbers can be cross-checked against ASA's during-tenure figures)."""
    rows = []
    for r in (tm.get(name, {}) or {}).get("seasons", []) or []:
        year = r.get("season")
        if year is None:
            continue
        rows.append(
            {
                "season": year,
                "season_label": r.get("season_label"),
                "team": r.get("club"),
                "league": r.get("competition"),
                "source": "transfermarkt",
                "phase": config.phase_for(year, tenure["start"], tenure["end"]),
                "transfermarkt": {
                    "apps": r.get("apps"),
                    "goals": r.get("goals"),
                    "assists": r.get("assists"),
                    "minutes": r.get("minutes"),
                },
            }
        )
    return rows


def apifootball_season_rows(name: str, af: dict, tenure: dict) -> list[dict]:
    rows = []
    for r in (af.get(name, {}) or {}).get("seasons", []) or []:
        year = r.get("season")
        if year is None:
            continue
        rows.append(
            {
                "season": year,
                "team": r.get("team"),
                "league": r.get("league"),
                "source": "apifootball",
                "phase": config.phase_for(year, tenure["start"], tenure["end"]),
                "apifootball": {
                    "apps": r.get("apps"),
                    "goals": r.get("goals"),
                    "assists": r.get("assists"),
                    "minutes": r.get("minutes"),
                },
            }
        )
    return rows


def worldfootball_season_rows(name: str, wf: dict, tenure: dict) -> list[dict]:
    rows = []
    for r in (wf.get(name, {}) or {}).get("seasons", []) or []:
        year = r.get("season")
        if year is None:
            continue
        rows.append(
            {
                "season": year,
                "season_label": r.get("season_label"),
                "team": r.get("club"),
                "league": r.get("comp"),
                "source": "worldfootball",
                "phase": config.phase_for(year, tenure["start"], tenure["end"]),
                "worldfootball": {
                    "apps": r.get("apps"),
                    "goals": r.get("goals"),
                    "assists": r.get("assists"),
                    "minutes": r.get("minutes"),
                },
            }
        )
    return rows


def merge_bios(per_source: dict[str, dict]) -> dict:
    """Collapse per-source bios into one, highest-trust-source-first per field."""
    merged: dict = {}
    for src in config.BIO_SOURCE_PRECEDENCE:
        for k, v in (per_source.get(src) or {}).items():
            if v not in (None, "") and k not in merged:
                merged[k] = v
    return merged


def asa_bios(asa_players: list[dict]) -> dict[str, dict]:
    """player_id -> bio from asa_players.json (first non-empty values win)."""
    out: dict[str, dict] = {}
    for r in asa_players:
        pid = str(r.get("player_id"))
        bio = out.setdefault(pid, {})
        if r.get("birth_date") and not bio.get("birth_date"):
            bio["birth_date"] = r["birth_date"]
        if r.get("nationality") and not bio.get("nationality"):
            bio["nationality"] = r["nationality"]
        pos = r.get("primary_general_position")
        if pos and not bio.get("position"):
            bio["position"] = pos
        ft, inch = r.get("height_ft"), r.get("height_in")
        if ft and not bio.get("height"):
            bio["height"] = f"{ft}'{inch or 0}\""
        if r.get("weight_lb") and not bio.get("weight"):
            bio["weight"] = f"{r['weight_lb']} lb"
    return out


def load_map(fname: str) -> dict:
    """Load a name-keyed raw file (Transfermarkt/Wikidata/etc.); {} if absent."""
    path = config.RAW_DIR / fname
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    print("Building data/players.json ...")
    asa_players_raw = load("asa_players.json")
    team_names = index_by_id(load("asa_teams.json"), "team_id", "team_name")
    player_names = index_by_id(asa_players_raw, "player_id", "player_name")
    xgoals = load("asa_player_xgoals.json")
    bios_asa = asa_bios(asa_players_raw)

    # Name-keyed cross-league / cross-check sources (each absent file -> no-op).
    fbref_careers = load_map("fbref_careers.json")
    wiki_careers = load_map("wikipedia_careers.json")
    transfermarkt = load_map("transfermarkt.json")
    apifootball = load_map("apifootball.json")
    worldfootball = load_map("worldfootball.json")
    wikidata = load_map("wikidata.json")
    thesportsdb = load_map("thesportsdb.json")

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

    # ASA per-season counting stats. The bucket is still named "xgoals" because it
    # comes from ASA's xgoals endpoint, but the modeled columns are dropped upstream
    # (fetch_asa.py) so only raw counts land here.
    for row in xgoals:
        s = slot(row)
        if s is not None:
            s["xgoals"] = {k: v for k, v in row.items() if k not in ("player_id", "season_name", "team_id")}

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
        # Layer in career context / cross-checks from every source (when available).
        # Rows stay tagged by source (never merged) so disagreements are visible.
        seasons.extend(fbref_season_rows(name, fbref_careers, tenure))
        seasons.extend(wiki_season_rows(name, wiki_careers, tenure))
        seasons.extend(tm_season_rows(name, transfermarkt, tenure))
        seasons.extend(apifootball_season_rows(name, apifootball, tenure))
        seasons.extend(worldfootball_season_rows(name, worldfootball, tenure))

        # Aggregate bio from every source (precedence in config); keep the raw
        # per-source bios alongside so mismatches can be inspected.
        bio_sources = {
            "asa": bios_asa.get(pid, {}),
            "transfermarkt": (transfermarkt.get(name, {}) or {}).get("bio", {}),
            "wikidata": (wikidata.get(name, {}) or {}).get("bio", {}),
            "thesportsdb": (thesportsdb.get(name, {}) or {}).get("bio", {}),
            "worldfootball": (worldfootball.get(name, {}) or {}).get("bio", {}),
        }
        bio_sources = {k: v for k, v in bio_sources.items() if v}

        player = {
            "player_id": f"asa:{pid}",
            "asa_id": pid,
            "name": name,
            "tenure": tenure,
            "bio": merge_bios(bio_sources),
            "bio_sources": bio_sources,
            "seasons": seasons,
        }
        # Player-level cross-check context that isn't per-season.
        wd = wikidata.get(name)
        if wd and wd.get("memberships"):
            player["wikidata_clubs"] = wd["memberships"]
        tsd = thesportsdb.get(name)
        if tsd and tsd.get("former_teams"):
            player["former_teams"] = tsd["former_teams"]
        if tsd and tsd.get("honours"):
            player["honours"] = tsd["honours"]
        players.append(player)

    # Layer manual wizard edits on top of the fetched data.
    players = apply_overrides(players, load_overrides())

    # Final stable ordering so output is byte-stable across runs.
    for p in players:
        p["seasons"].sort(key=SEASON_SORT_KEY)
    players.sort(key=lambda p: (p["name"] or "", p["player_id"]))
    out = {
        "club": config.CLUB_NAME,
        "sources": [
            "asa", "wikipedia", "fbref", "transfermarkt",
            "apifootball", "worldfootball", "wikidata", "thesportsdb",
        ],
        "player_count": len(players),
        "players": players,
    }
    path = config.DATA_DIR / "players.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {path.relative_to(config.ROOT)} ({len(players)} players)")


if __name__ == "__main__":
    main()
