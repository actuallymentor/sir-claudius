#!/bin/bash

# Mark the bind-mounted workspace as a safe git directory.
# The host UID rarely matches the container's node user, which makes git
# refuse to operate ("dubious ownership"). The container itself is the
# security boundary, so this is safe.
git config --global --add safe.directory /workspace

# Fix ownership on the isolated node_modules volume.
# Docker seeds named volumes from the mount point, copying host-owned files
# (e.g. UID 501 on macOS). The container's node user (UID 1000) can't modify
# these without a chown. The CLAUDIUS_NM_ISOLATED gate ensures this only runs
# when the named volume overlay is active (not on the raw bind mount).
if [ "${CLAUDIUS_NM_ISOLATED:-0}" = "1" ] && [ -d /workspace/node_modules ]; then
    sudo chown -R node:node /workspace/node_modules 2>/dev/null || true
fi

# Wrap through auto-accept.py when yolo (plan auto-accept) or loop
# (periodic re-prompting) is active. Autopilot only manages tmux.
if [ "${CLAUDIUS_YOLO:-}" = "1" ] || [ "${CLAUDIUS_LOOP:-}" = "1" ]; then
    exec python3 /usr/local/bin/auto-accept.py "$@"
else
    exec "$@"
fi
