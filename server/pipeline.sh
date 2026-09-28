#!/usr/bin/env bash
# Runs inside the pipeline container (cwd /repo/scripts). Mirrors the steps of
# .github/workflows/update-data.yml: ASA + Wikipedia + build are required, every
# other source is best-effort so one flaky source never blocks a refresh.
set -uo pipefail

required() {
  echo "=== $1"
  python "$1" || { echo "!!! required step $1 failed"; exit 1; }
}

optional() {
  echo "=== $1"
  python "$1" || echo "--- $1 failed (best-effort, continuing)"
}

required fetch_asa.py
required fetch_wikipedia.py

# The API container takes a few seconds to come up; don't burn the fetch on it.
for _ in $(seq 1 30); do
  python -c "import requests,os; requests.get(os.environ['TRANSFERMARKT_API'], timeout=3)" 2>/dev/null && break
  sleep 2
done
optional fetch_transfermarkt.py
optional fetch_fbref.py
optional fetch_wikidata.py
optional fetch_thesportsdb.py
optional fetch_apifootball.py
optional fetch_worldfootball.py

required build_players.py
