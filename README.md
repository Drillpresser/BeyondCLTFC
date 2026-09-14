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
| [American Soccer Analysis (ASA)](https://app.americansocceranalysis.com) | MLS per-season stats (goals, shots, assists, minutes) during CLTFC tenure | Public API (`itscalledsoccer`) |
| [Transfermarkt](https://www.transfermarkt.com) | **Primary** cross-league career stats (apps/goals/assists/minutes by competition & season) + bio | Self-hosted [`felipeall/transfermarkt-api`](https://github.com/felipeall/transfermarkt-api) over HTTP |
| [Wikipedia](https://en.wikipedia.org) | Cross-league career season stats (before/after) | MediaWiki API + `pandas.read_html` |
| [Wikidata](https://www.wikidata.org) | Bio + club-membership timelines (with match/goal counts) for tenure cross-check | SPARQL (ToS-clean, any IP) |
| [TheSportsDB](https://www.thesportsdb.com) | Bio, photos, former teams, honours | Free JSON API |
| [API-FOOTBALL](https://www.api-football.com) | Sanctioned MLS/Liga MX/Europe per-season backstop | REST API (free key, 100 req/day) |
| [worldfootballR](https://github.com/JaseZiv/worldfootballR) | Independent FBref + Transfermarkt cross-read (R) | R package via `Rscript` |
| [FBref](https://fbref.com) | Extra career context (apps, goals, minutes), best-effort | Scraped player pages (`curl_cffi`) |

> **Aggregation, on purpose.** This project deliberately pulls the *same* facts
> (per-season apps/goals/minutes, bio, club tenure) from several independent
> sources. `build_players.py` keeps every source's rows **tagged and un-merged**,
> and collapses bio only into a `bio` field while preserving each source's values
> in `bio_sources` — so disagreements are *visible and checkable*, not silently
> trusted. The goal is correctness through corroboration.

> **Counting stats only.** ASA's and FBref's modeled/predictive metrics — expected
> goals and the whole x-family (xG, xA, xG+xA, …) plus ASA's goals-added (g+) and
> points-added value models — are intentionally **not** gathered.

**Coverage:** ASA gives MLS per-season stats; Transfermarkt is the primary cross-league
career source (Europe, Liga MX, lower divisions — far deeper than Wikipedia), with Wikipedia,
Wikidata, TheSportsDB, API-FOOTBALL and worldfootballR layered in for corroboration and to
fill gaps for academy/fringe players. Every source except ASA/Wikipedia/build is best-effort
(`continue-on-error` in CI): a flaky source never blocks a refresh.

> **Source notes / lessons learned:**
> - **Transfermarkt** is the deepest career source. The site is JS-rendered with an
>   obfuscated internal API, so we don't scrape it directly — we run a self-hosted
>   [`felipeall/transfermarkt-api`](https://github.com/felipeall/transfermarkt-api)
>   container and query it over HTTP (`TRANSFERMARKT_API`, default `http://localhost:8000`).
>   Running it in-process/in-job sidesteps shared-instance rate limits and datacenter-IP
>   blocking. *(Note: scraping Transfermarkt is against their ToS — same category as FBref.)*
> - **Wikidata** is ToS-clean (SPARQL) and reliable from any IP — ideal for bio and
>   club-tenure timelines, though per-season goal splits are sparse.
> - **Wikipedia** is server-rendered, ToS-clean, no anti-bot layer, reliable in CI; covers
>   apps/goals per club/season across a full career.
> - **API-FOOTBALL** is a sanctioned REST API (no scraping, any IP). Free tier is 100 req/day
>   and restricts which seasons you can query — set `APIFOOTBALL_KEY` and `APIFOOTBALL_SEASONS`.
> - **TheSportsDB** is free and crowd-sourced: quality varies (treat as a supplement), good
>   for photos/bio/former-teams.
> - **worldfootballR** (R) is an independent read of FBref + Transfermarkt for corroboration;
>   skipped unless `Rscript` + the package are installed.
> - **FBref** sits behind Cloudflare and is frequently **403-blocked** from datacenter IPs
>   even with `curl_cffi`. With xG removed it's demoted to a best-effort cross-check.

## Layout

```
scripts/                 Python fetch + build pipeline
  requirements.txt
  config.py              CLTFC identity, tenure boundaries, phase logic, source config
  fetch_asa.py           ASA API        -> data/raw/asa_*.json
  fetch_transfermarkt.py Transfermarkt  -> data/raw/transfermarkt.json (self-hosted API)
  fetch_wikipedia.py     Wikipedia      -> data/raw/wikipedia_careers.json
  fetch_wikidata.py      Wikidata SPARQL-> data/raw/wikidata.json (bio + club timelines)
  fetch_thesportsdb.py   TheSportsDB    -> data/raw/thesportsdb.json (bio, former teams)
  fetch_apifootball.py   API-FOOTBALL   -> data/raw/apifootball.json (needs APIFOOTBALL_KEY)
  fetch_worldfootball.py → fetch_worldfootball.R -> data/raw/worldfootball.json (needs R)
  fetch_fbref.py         FBref          -> data/raw/fbref_careers.json (best-effort)
  build_players.py       merge raw      -> data/players.json (site consumes this)
data/                    committed JSON output (the "database")
  raw/                   per-source raw pulls
  players.json           unified, site-facing dataset
  overrides.json         manual edits (from the wizard), merged by the build
editor/                  standalone local record-editing wizard (own package.json; never deployed)
web/                     React + Vite front-end (GitHub Pages)
.github/workflows/       scheduled update Action
```

## Local development

```bash
# 1. Fetch + build data
cd scripts
python -m venv .venv && . .venv/Scripts/activate   # Windows; use .venv/bin/activate on *nix
pip install -r requirements.txt

python fetch_asa.py           # MLS per-season stats (required)
python fetch_wikipedia.py     # cross-league career context (before/after)
python fetch_wikidata.py      # bio + club timelines (ToS-clean SPARQL)
python fetch_thesportsdb.py   # bio, photos, former teams, honours

# Transfermarkt (primary career source): start the self-hosted API first, then fetch.
docker run -d --name tmkt -p 8000:8000 felipeall/transfermarkt-api:latest
python fetch_transfermarkt.py            # uses TRANSFERMARKT_API (default localhost:8000)

# Optional cross-checks (skip cleanly if unavailable):
APIFOOTBALL_KEY=xxx python fetch_apifootball.py   # sanctioned API; free key, 100 req/day
python fetch_worldfootball.py            # needs R + install.packages(c("worldfootballR","jsonlite"))
python fetch_fbref.py                    # best-effort; may be Cloudflare-blocked

python build_players.py       # merges whatever raw files are present

# 2. Run the site
cd ../web
npm install
mkdir -p public/data && cp ../data/players.json public/data/   # dev reads from public/
npm run dev
```

All fetches are independent and cache to `data/raw/`, so you can run any subset — the
build merges whatever is present. Set the `APIFOOTBALL_KEY` repo secret to enable
API-FOOTBALL in CI; leave it unset to skip that source.

In production the `deploy-site.yml` workflow copies `data/` into the build, so the
site fetches `./data/players.json` in both dev and prod.

## Editing player records (the wizard)

The site is static (no backend to write to), so manual edits live in a committed
**overrides layer**: `data/overrides.json`. `build_players.py` merges it *on top of* the
fetched (and cross-checked) source data, so your edits survive every re-fetch (they're
re-applied, not overwritten) and are reviewable in git.

The wizard is a **standalone local tool**, deliberately kept separate from the site in
`web/`: it has its own `package.json`, isn't part of the Vite build or the deploy
workflow, and needs a writable checkout (it saves `overrides.json` and can rebuild
`players.json`), so it only ever runs on your own machine. Run it:

```bash
cd editor
npm start           # starts the local editor → http://localhost:4321
                    # (no dependencies — uses only Node built-ins)
```

The wizard walks through: pick a player (or add a new manual one) → **bio & tenure** →
**correct fetched stats** → **add seasons the sources miss** → review → save. Saving writes
`data/overrides.json`; the "Rebuild" button runs `build_players.py` so you can review the
merged `data/players.json` before committing both files. The editor is local-only — it is
never deployed.

**Overrides never mutate source stats** — a corrected value goes in a season's `override`
bucket that the UI prefers, so the original stays visible in git and the app. Overriding a
player's `tenure` re-tags all their seasons' before/during/after phases. This layer also
supersedes the (now-optional) hand-edited `TENURES` block in `config.py`.

`data/overrides.json` schema:

```jsonc
{
  "players": {                          // edits to players that exist in the sources
    "asa:<id>": {
      "bio":     { "position": "...", "nationality": "...", "photo_url": "...", "notes": "..." },
      "tenure":  { "start": 2022, "end": 2024 },        // end: null = still at club
      "season_overrides": [                              // correct a fetched value
        { "season": 2019, "source": "wikipedia", "team": "Leicester City", "patch": { "goals": 3 } }
      ],
      "added_seasons": [                                 // a season the sources miss
        { "season": 2016, "team": "UNC Charlotte", "league": "NCAA", "apps": 18, "goals": 4 }
      ]
    }
  },
  "added_players": [                     // players not in any source at all
    { "player_id": "manual:...", "name": "...", "tenure": {...}, "bio": {...}, "seasons": [...] }
  ]
}
```

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
