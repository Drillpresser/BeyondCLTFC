# Home-server data refresh

The weekly refresh runs on the home server (`trinary`) instead of GitHub Actions.
From a residential IP, FBref doesn't 403 every request. Transfermarkt also gets to
run here: its API image isn't on Docker Hub, so it's built from source.

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
| `~/.config/beyondcltfc.env` | Optional secrets: `APIFOOTBALL_KEY=...`, `APIFOOTBALL_SEASONS=...` |
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
