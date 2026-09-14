# BeyondCLTFC

Tracks Charlotte FC (MLS) players and their career stats, with a focus on comparing
each player's performance **before**, **during**, and **after** their stint with the club.

## How it works

This project uses the "git scraping" pattern: a scheduled GitHub Action runs the Python
fetch scripts, writes the results as JSON into [`data/`](data/), and commits them back to
the repo. GitHub Pages then serves both the static site (`web/`) and the JSON data. Every
scheduled commit is a snapshot, so **git history is the time series** — no database needed.

## Data sources

| Source | Used for | Access |
| --- | --- | --- |
| [American Soccer Analysis (ASA)](https://app.americansocceranalysis.com) | MLS advanced stats (xG, g+) during CLTFC tenure | Public API (`itscalledsoccer`) |
| [FBref](https://fbref.com) | Cross-league career season stats (before/after) | Scraped via `soccerdata` |
| [Transfermarkt](https://www.transfermarkt.com) | Roster + arrival/departure timeline | Scraped (BeautifulSoup) |

> ⚠️ FBref and Transfermarkt scraping is against their strict ToS but common for
> personal, non-commercial use. Keep request rates low; all scrapers here cache and throttle.
> ASA is an open, sanctioned API.

## Layout

```
scripts/                 Python fetch + build pipeline
  requirements.txt
  config.py              CLTFC identity, tenure boundaries, phase logic
  fetch_asa.py           ASA API  -> data/raw/asa_*.json
  fetch_fbref.py         FBref     -> data/raw/fbref_*.json
  fetch_transfermarkt.py Transfermarkt roster -> data/raw/transfermarkt_squad.json
  build_players.py       merge raw -> data/players.json (site consumes this)
data/                    committed JSON output (the "database")
  raw/                   per-source raw pulls
  players.json           unified, site-facing dataset
web/                     React + Vite front-end (GitHub Pages)
.github/workflows/       scheduled update Action
```

## Local development

```bash
# 1. Fetch + build data
cd scripts
python -m venv .venv && . .venv/Scripts/activate   # Windows; use .venv/bin/activate on *nix
pip install -r requirements.txt
python fetch_asa.py
python fetch_fbref.py
python fetch_transfermarkt.py
python build_players.py

# 2. Run the site
cd ../web
npm install
mkdir -p public/data && cp ../data/players.json public/data/   # dev reads from public/
npm run dev
```

In production the `deploy-site.yml` workflow copies `data/` into the build, so the
site fetches `./data/players.json` in both dev and prod.

## The before / during / after model

`config.py` defines each player's CLTFC tenure (arrival/departure season). Every season
row is tagged with a `phase` of `before`, `during`, or `after` relative to that tenure,
which is the axis the whole comparison UI is built around.

**Important curation note:** `before` is detected automatically (any pre-2022 season is
correctly `before`). But `after` requires an `end` year in `config.TENURES` — with the
default `end: None`, a player who left CLTFC and reappears at another MLS club (e.g. Ben
Bender → Philadelphia in 2025) is still tagged `during`. Run `fetch_transfermarkt.py` to
get the roster, then set real `end` years in `TENURES` so departures classify as `after`.
These windows are hand-editable on purpose: they live in git, are reviewable, and make the
phase logic deterministic.
