#!/bin/bash

# Fix ownership of the isolated node_modules Docker volume.
# When Docker seeds a named volume from a bind-mounted path, it copies
# host-owned files (e.g., macOS UID 501) that the container's node user
# (UID 1000) cannot modify. Only runs when the isolation volume is active
# (not on the raw bind mount, which would change ownership on the host).
if [ "${CLAUDIUS_NM_ISOLATED:-0}" = "1" ] && [ -d /workspace/node_modules ]; then
    sudo chown -R node:node /workspace/node_modules 2>/dev/null || true
fi

exec "$@"
