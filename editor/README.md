# Player editor

A wizard for fixing player records by hand: bio, Charlotte FC tenure, corrected
season stats, extra seasons the sources don't have, and whole players that
aren't in ASA. Edits go into `data/overrides.json`. `build_players.py` layers
them over the fetched data without changing the source rows, so the original
values stay visible in git.

Only fields you change (or had already overridden) are saved. Everything else
keeps updating from the weekly refresh. For example, fixing a height doesn't pin
the automatically derived tenure.

## On the home server: https://cltfc-editor.lan

Runs in Docker on trinary behind Caddy, which asks for a password. Each save
**publishes**: the editor resets its clone to `origin/master`, writes the
overrides, rebuilds `players.json`, commits both and pushes. The site redeploys
in about a minute, and the weekly refresh keeps the edit. If the refresh pushed
first, the editor starts over from the new `master` (up to 3 tries).

| Path on trinary | What |
|---|---|
| `~/beyondcltfc-editor/` | The editor's own clone. Don't work in it; it's reset before every read and save. |
| `~/.ssh/beyondcltfc_deploy` | Deploy key it pushes with (mounted read-only). |
| `~/beyondcltfc-editor.password` | The Caddy login password (user `tyler`). |

Update to the latest code and restart:

```bash
ssh homeserver 'cd ~/beyondcltfc-editor && git pull -q && docker compose -f editor/docker-compose.yml up -d --build'
```

Logs: `ssh homeserver docker logs --tail 50 beyondcltfc-editor`

The Caddy site block and the AdGuard DNS rewrite for `cltfc-editor.lan` live in
the AppHub project.

## Locally

```bash
cd editor && npm start      # http://localhost:4321
```

Saves only write `data/overrides.json`. Use **Rebuild** to regenerate
`players.json`, then commit both yourself.
