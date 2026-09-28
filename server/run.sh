#!/usr/bin/env bash
# Weekly data refresh on the home server, run from cron (see server/README.md).
# Everything is inside main() so bash parses the whole file before the git
# reset below can rewrite it mid-run.
#   BRANCH=<name>  branch to refresh (default master)
#   PUSH=0         commit locally but don't push (for testing)
set -euo pipefail

main() {
  local repo branch push rc=0
  repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  branch="${BRANCH:-master}"
  push="${PUSH:-1}"
  cd "$repo"

  exec 9>/tmp/beyondcltfc-refresh.lock
  flock -n 9 || { echo "Another refresh is running; exiting."; exit 0; }

  echo "### $(date -u +%FT%TZ) refresh of $branch"
  # This clone belongs to the bot: always start from exactly what's on GitHub.
  git fetch --quiet origin
  git checkout --quiet -f -B "$branch" "origin/$branch"
  git clean -fdq data/

  # --profile run so the pipeline service is included in build/down too.
  local compose=(docker compose -f server/docker-compose.yml --profile run --progress quiet)
  "${compose[@]}" build --pull
  "${compose[@]}" run --rm --user "$(id -u):$(id -g)" pipeline || rc=$?
  "${compose[@]}" down
  if [ "$rc" -ne 0 ]; then
    echo "### pipeline failed (exit $rc); nothing committed"
    exit "$rc"
  fi

  git add data/
  if git diff --staged --quiet; then
    echo "### no data changes"
    return
  fi
  git -c user.name=beyondcltfc-bot -c user.email=beyondcltfc-bot@users.noreply.github.com \
    commit --quiet -m "data: refresh $(date -u +%F)"
  if [ "$push" = 1 ]; then
    git push --quiet origin "$branch"
    echo "### pushed $(git rev-parse --short HEAD)"
  else
    echo "### committed $(git rev-parse --short HEAD) locally (PUSH=0)"
  fi
}

main "$@"
