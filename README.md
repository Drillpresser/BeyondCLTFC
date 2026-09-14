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
| [Wikipedia](https://en.wikipedia.org) | Cross-league career season stats (before/after) | MediaWiki API + `pandas.read_html` |
| [FBref](https://fbref.com) | Extra career context (apps, goals, minutes), best-effort | Scraped player pages (`curl_cffi`) |

> **Note:** We collect only raw counting stats. ASA's and FBref's modeled/predictive
> metrics — expected goals and the whole x-family (xG, xA, xG+xA, …) plus ASA's
> goals-added (g+) and points-added value models — are intentionally **not** gathered.

**Coverage:** ASA gives MLS per-season stats; Wikipedia's "Career statistics" tables give the
cross-league before/after seasons (Europe, Liga MX, etc.) that ASA can't see. As of the last
run, **56 of 74** players have Wikipedia career data (the rest are academy/fringe players
without detailed tables — ASA still covers their MLS minutes).

> **Source notes / lessons learned:**
> - **Wikipedia** is the primary career source: server-rendered, ToS-clean (CC BY-SA + public
>   API), no anti-bot layer, and reliable in CI. It covers apps/goals per club/season across
>   a full career.
> - **FBref** sits behind Cloudflare and is frequently **403-blocked** from datacenter IPs
>   (GitHub Actions) even with `curl_cffi` TLS impersonation. It's kept as a best-effort,
>   `continue-on-error` step for extra career context when the IP isn't flagged.
> - **Transfermarkt** is *no longer used*: the site went fully JS-rendered and its stats now
>   load from an undocumented, obfuscated internal API — impractical for static scraping.

## Layout

```
scripts/                 Python fetch + build pipeline
  requirements.txt
  config.py              CLTFC identity, tenure boundaries, phase logic
  fetch_asa.py           ASA API   -> data/raw/asa_*.json
  fetch_wikipedia.py     Wikipedia -> data/raw/wikipedia_careers.json (cross-league careers)
  fetch_fbref.py         FBref     -> data/raw/fbref_careers.json (best-effort)
  build_players.py       merge raw -> data/players.json (site consumes this)
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
python fetch_asa.py         # MLS advanced stats (required)
python fetch_wikipedia.py   # cross-league career context (before/after)
python fetch_fbref.py       # optional extra xG; may be Cloudflare-blocked
python build_players.py

# 2. Run the site
cd ../web
npm install
mkdir -p public/data && cp ../data/players.json public/data/   # dev reads from public/
npm run dev
```

In production the `deploy-site.yml` workflow copies `data/` into the build, so the
site fetches `./data/players.json` in both dev and prod.

## Editing player records (the wizard)

The site is static (no backend to write to), so manual edits live in a committed
**overrides layer**: `data/overrides.json`. `build_players.py` merges it *on top of* the
fetched ASA/Wikipedia/FBref data, so your edits survive every re-fetch (they're re-applied,
not overwritten) and are reviewable in git.

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
