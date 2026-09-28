# Home-server data refresh

The weekly refresh runs on the home server (`trinary`) instead of GitHub Actions.
The image uses `rocker/r-ver`, so worldfootballR installs from prebuilt binaries
(on the GitHub runner it failed to compile).

Findings from the first test run (2026-09-28), with the same blocks seen from the home IP:
- **FBref** returns Cloudflare 403s here too, so `fetch_fbref.py` is turned off. worldfootballR now takes its roster from ASA and finds FBref URLs through its own player dictionary.
- **Transfermarkt**: the API has to be built from source (it isn't on Docker Hub). Its
  stats endpoint returned no rows, and Transfermarkt 403'd the house IP after about 12
  players. It is now **opt-in**, including worldfootballR bios: add `ENABLE_TRANSFERMARKT=1` to the env file below.

```
cron (Mon 09:17 UTC) → server/run.sh
  ├─ git fetch + hard reset to origin/master       (the clone belongs to the bot)
  ├─ docker compose build                           (pipeline image + transfermarkt-api)
  ├─ docker compose run pipeline → server/pipeline.sh (same steps as update-data.yml)
  └─ commit data/ → git push                        (push triggers deploy-site.yml)
```

## Layout on the server

| Path | What |
|---|---|
| `~/beyondcltfc/` | Dedicated clone. Don't edit it; each run resets it to `origin/master`. |
| `~/.ssh/beyondcltfc_deploy` | Deploy key with write access to this repo only; the clone's `core.sshCommand` uses it. |
| `~/.config/beyondcltfc.env` | Optional: `APIFOOTBALL_KEY=...`, `APIFOOTBALL_SEASONS=...`, `ENABLE_TRANSFERMARKT=1` |
| `~/beyondcltfc-logs/refresh.log` | Cron output, appended each run. |

Crontab (`crontab -l`):

```
17 9 * * 1 $HOME/beyondcltfc/server/run.sh >> $HOME/beyondcltfc-logs/refresh.log 2>&1
```

## Common tasks

```bash
ssh homeserver
~/beyondcltfc/server/run.sh                          # refresh now
PUSH=0 ~/beyondcltfc/server/run.sh                   # dry run: commit locally, don't push
BRANCH=some-branch PUSH=0 ~/beyondcltfc/server/run.sh # test a branch's pipeline
tail -100 ~/beyondcltfc-logs/refresh.log
```

The GitHub `update-data.yml` workflow is still there for manual runs (Actions tab →
Run workflow), but it no longer has a schedule.
