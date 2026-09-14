"""Shared configuration for the BeyondCLTFC data pipeline.

The single source of truth for *who* counts as a Charlotte FC player and *when* they
were at the club. The per-player tenure windows here drive the before/during/after
phase tagging in build_players.py.
"""
from __future__ import annotations

from pathlib import Path

# --- Paths ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# --- Club identity ----------------------------------------------------------
# Charlotte FC joined MLS as an expansion side for the 2022 season.
CLUB_NAME = "Charlotte FC"
CLUB_FIRST_SEASON = 2022

# ASA (American Soccer Analysis) resolves team_id at runtime by name match,
# so we only need the display name it uses.
ASA_LEAGUE = "mls"
ASA_TEAM_NAME_CONTAINS = "Charlotte"

# FBref league string as used by the `soccerdata` package.
FBREF_LEAGUE = "USA-Major League Soccer"

# Transfermarkt squad page. The numeric id (30012) is Charlotte FC.
TRANSFERMARKT_SQUAD_URL = (
    "https://www.transfermarkt.com/charlotte-fc/kader/verein/30012"
)

# Seasons to pull. Extend the upper bound each year (or compute from date).
SEASONS = [str(y) for y in range(CLUB_FIRST_SEASON, 2027)]

# --- Player tenure windows --------------------------------------------------
# season is inclusive; `end=None` means still at the club.
# This is intentionally editable by hand: Transfermarkt gives us a starting
# roster, but the authoritative arrival/departure years live here so the
# before/during/after logic is deterministic and reviewable in git.
#
# Fill/adjust these as the roster is confirmed. `fetch_transfermarkt.py` prints
# a suggested block you can paste in.
TENURES: dict[str, dict[str, int | None]] = {
    # "Player Name": {"start": 2022, "end": None},
}


def phase_for(season: int, start: int, end: int | None) -> str:
    """Classify a season relative to a player's CLTFC tenure."""
    if season < start:
        return "before"
    if end is not None and season > end:
        return "after"
    return "during"


# --- HTTP politeness ---------------------------------------------------------
USER_AGENT = "BeyondCLTFC/0.1 (personal, non-commercial; +https://github.com/)"
REQUEST_DELAY_SECONDS = 3.0  # be gentle with scraped sources
