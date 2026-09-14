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

# Wikipedia — the cross-league career-stats source (server-rendered, ToS-clean).
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "https://en.wikipedia.org/wiki/"
WIKI_USER_AGENT = "BeyondCLTFC/0.1 (personal, non-commercial soccer stats project)"
WIKI_DELAY_SECONDS = 0.5  # Wikipedia is scrape-friendly; just be reasonable

# --- Additional cross-league sources (aggregated for cross-validation) ---------
# The project deliberately pulls the *same* facts (per-season apps/goals/minutes,
# bio, club tenure) from several independent sources so build_players.py can keep
# them side by side and disagreements are visible rather than silently trusted.

# Wikidata — structured, ToS-clean SPARQL endpoint. Great for bio + club
# membership timelines (P54) with match counts (P1350). Reliable from any IP.
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# TheSportsDB — free, crowd-sourced JSON API. Good for bio, photos, former teams
# and honours. "3" is the shared public test key; set THESPORTSDB_KEY for your own.
import os  # noqa: E402 - kept local to the config section that uses it

THESPORTSDB_KEY = os.environ.get("THESPORTSDB_KEY", "3")
THESPORTSDB_API = f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_KEY}"

# Transfermarkt — revived via a self-hosted felipeall/transfermarkt-api container
# (see README). We query it over HTTP so nothing here scrapes Transfermarkt
# directly. Point TRANSFERMARKT_API at your running instance.
TRANSFERMARKT_API = os.environ.get("TRANSFERMARKT_API", "http://localhost:8000").rstrip("/")

# API-FOOTBALL (api-sports.io) — sanctioned REST API, covers MLS + Liga MX +
# Europe. Needs a free key in APIFOOTBALL_KEY; skipped entirely when unset.
APIFOOTBALL_KEY = os.environ.get("APIFOOTBALL_KEY", "")
APIFOOTBALL_API = "https://v3.football.api-sports.io"

# Order used when collapsing bio fields from multiple sources into one value.
# Earlier = higher trust. (Season stat rows are never collapsed — every source's
# rows are kept and tagged so the app can compare them.)
BIO_SOURCE_PRECEDENCE = ("transfermarkt", "wikidata", "asa", "thesportsdb", "apifootball")

# Seasons to pull. Extend the upper bound each year (or compute from date).
SEASONS = [str(y) for y in range(CLUB_FIRST_SEASON, 2027)]

# --- Player tenure windows --------------------------------------------------
# season is inclusive; `end=None` means still at the club.
# This is intentionally editable by hand: the ASA roster tells us who played
# for CLTFC, but the authoritative arrival/departure years live here so the
# before/during/after logic is deterministic and reviewable in git.
# Fill/adjust these as the roster is confirmed.
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
