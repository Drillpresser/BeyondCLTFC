# Player editor for the home server (see editor/README.md). build_players.py only
# uses the standard library, so this is plain Python plus Node for the server and
# git/ssh for publishing.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs git openssh-client ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Runs as the host user, so give git a writable HOME.
ENV HOME=/tmp \
    PYTHONUTF8=1 \
    EDITOR_PUBLISH=1 \
    GIT_SSH_COMMAND="ssh -i /keys/deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/keys/known_hosts"

WORKDIR /repo/editor
EXPOSE 4321
CMD ["node", "server.mjs"]
