"""Fetch MLS per-season stats from American Soccer Analysis (ASA).

Strategy:
  1. Resolve the Charlotte FC team_id by name.
  2. Find every player who logged CLTFC minutes in any tracked season.
  3. Pull those players' full MLS career (all teams, all seasons), split by
     season *and* team. Splitting by team is what lets us later see a player's
     MLS stats at *other* clubs (i.e. their "before"/"after" MLS phases), not
     just at Charlotte.

We keep only raw counting stats (goals, shots, assists, minutes, ...). ASA's
modeled/predictive metrics (expected goals and the whole x-family, plus the
goals-added / points-added value models) are intentionally dropped — see
MODELED_COLUMNS below.

Writes:
  data/raw/asa_teams.json
  data/raw/asa_players.json         (id -> name lookup)
  data/raw/asa_player_xgoals.json
"""
from __future__ import annotations

import json
import sys

import config

try:
    from itscalledsoccer.client import AmericanSoccerAnalysis
except ImportError:
    sys.exit("itscalledsoccer not installed. Run: pip install -r requirements.txt")


# ASA's xG/g+ model returns last-decimal jitter between calls (e.g. 5.9361 vs
# 5.936), and doesn't guarantee row order. Round floats and sort canonically so
# the committed files are byte-stable and don't churn on every scheduled run.
FLOAT_PRECISION = 3

# Modeled / predictive columns we deliberately do NOT keep: expected goals and
# the rest of the x-family, the actual-minus-expected diffs, and the points-added
# value metrics. Only raw counting stats survive. `errors="ignore"` on the drop
# means this stays safe if ASA renames or omits any of these.
MODELED_COLUMNS = [
    "xgoals",
    "xplace",
    "goals_minus_xgoals",
    "xassists",
    "primary_assists_minus_xassists",
    "xgoals_plus_xassists",
    "points_added",
    "xpoints_added",
]


def drop_modeled(df):
    """Strip modeled/predictive columns so only raw counting stats are written."""
    if df is None or len(df) == 0:
        return df
    return df.drop(columns=MODELED_COLUMNS, errors="ignore")


def _round_floats(obj):
    if isinstance(obj, float):
        return round(obj, FLOAT_PRECISION)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    return obj


def df_to_records(df) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    # normalise numpy/NaN into JSON-safe values
    records = [_round_floats(r) for r in json.loads(df.to_json(orient="records"))]
    records.sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return records


def write(name: str, data) -> None:
    path = config.RAW_DIR / f"asa_{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {path.relative_to(config.ROOT)} ({len(data)} rows)")


def main() -> None:
    asa = AmericanSoccerAnalysis()
    league = config.ASA_LEAGUE

    print("Resolving Charlotte FC team_id...")
    teams = asa.get_teams(leagues=league)
    write("teams", df_to_records(teams))

    match = teams[
        teams["team_name"].str.contains(config.ASA_TEAM_NAME_CONTAINS, case=False, na=False)
    ]
    if match.empty:
        sys.exit(f"Could not find a team matching '{config.ASA_TEAM_NAME_CONTAINS}' in ASA.")
    cltfc_id = str(match.iloc[0]["team_id"])
    print(f"  Charlotte FC team_id = {cltfc_id} ({match.iloc[0]['team_name']})")

    # Step 2: who played for CLTFC in any tracked season?
    print("Finding CLTFC roster across seasons...")
    cltfc_xg = asa.get_player_xgoals(
        leagues=league,
        team_id=[cltfc_id],
        season_name=config.SEASONS,
        split_by_seasons=True,
    )
    if cltfc_xg is None or len(cltfc_xg) == 0:
        sys.exit("No CLTFC player rows returned from ASA; nothing to fetch.")
    player_ids = sorted({str(p) for p in cltfc_xg["player_id"].tolist()})
    print(f"  found {len(player_ids)} distinct CLTFC-associated players")

    # Player id -> name lookup (only the relevant players).
    players = asa.get_players(leagues=league, ids=player_ids)
    write("players", df_to_records(players))

    # Step 3: full MLS career for those players, split by season & team.
    # (The xgoals endpoint is also ASA's per-season counting-stats table; we keep
    # the raw columns from it and drop the modeled ones.)
    print("Fetching full MLS career...")
    career = asa.get_player_xgoals(
        leagues=league,
        player_id=player_ids,
        split_by_seasons=True,
        split_by_teams=True,
    )
    write("player_xgoals", df_to_records(drop_modeled(career)))

    print("ASA fetch complete.")


if __name__ == "__main__":
    main()
