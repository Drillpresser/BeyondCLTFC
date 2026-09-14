"""Fetch cross-league career season stats from FBref via `soccerdata`.

FBref is our source for a player's stats *outside* MLS (their pre-CLTFC and
post-CLTFC clubs in Europe, Liga MX, etc.), which ASA does not cover.

soccerdata handles caching and throttling. FBref rate-limits aggressively
(~1 request / 3s and will block bursts), so this script only pulls
MLS league-season tables here; extending to a player's *full* career means
scraping individual FBref player pages, which is stubbed below with the
recommended approach.

Writes:
  data/raw/fbref_mls_standard_<season>.json   (per season)
"""
from __future__ import annotations

import json
import sys

import config

try:
    import soccerdata as sd
except ImportError:
    sys.exit("soccerdata not installed. Run: pip install -r requirements.txt")


def df_to_records(df) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    # FBref tables have a MultiIndex header; flatten before serialising.
    flat = df.copy()
    flat.columns = [
        "_".join(str(c) for c in col if str(c) != "").strip("_")
        if isinstance(col, tuple)
        else str(col)
        for col in flat.columns
    ]
    flat = flat.reset_index()
    return json.loads(flat.to_json(orient="records"))


def main() -> None:
    for season in config.SEASONS:
        print(f"FBref: MLS standard stats {season}...")
        try:
            fbref = sd.FBref(leagues=config.FBREF_LEAGUE, seasons=season)
            df = fbref.read_player_season_stats(stat_type="standard")
        except Exception as exc:  # noqa: BLE001 - network/scrape failures are expected
            print(f"  skipped {season}: {exc}")
            continue

        records = df_to_records(df)
        path = config.RAW_DIR / f"fbref_mls_standard_{season}.json"
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {path.relative_to(config.ROOT)} ({len(records)} rows)")

    print("FBref fetch complete.")
    print(
        "\nNOTE: for full cross-league career histories, scrape individual FBref\n"
        "player pages (fbref.com/en/players/<id>/) — each lists every season at\n"
        "every club. Resolve player ids from Transfermarkt/ASA names, then read\n"
        "the 'Standard Stats' table per player. Keep the 3s delay to avoid bans."
    )


if __name__ == "__main__":
    main()
