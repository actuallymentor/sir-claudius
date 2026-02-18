#!/bin/bash

# Fix ownership on the isolated node_modules volume.
# Docker seeds named volumes from the mount point, copying host-owned files
# (e.g. UID 501 on macOS). The container's node user (UID 1000) can't modify
# these without a chown. The CLAUDIUS_NM_ISOLATED gate ensures this only runs
# when the named volume overlay is active (not on the raw bind mount).
if [ "${CLAUDIUS_NM_ISOLATED:-0}" = "1" ] && [ -d /workspace/node_modules ]; then
    sudo chown -R node:node /workspace/node_modules 2>/dev/null || true
fi

exec "$@"
