#!/bin/sh
# start.sh — launch uvicorn.
#
# PocketBase now runs in a separate container (see pocketbase/ service).
# FastAPI connects to it via PB_URL (e.g. http://pocketbase:8090).
#
# Environment variables consumed here:
#   UVICORN_RELOAD   Set to "true" to enable hot-reload (dev only)

set -e

RELOAD_FLAG=""
if [ "${UVICORN_RELOAD:-false}" = "true" ]; then
    RELOAD_FLAG="--reload"
    echo "Hot-reload enabled (UVICORN_RELOAD=true)"
fi

echo "Starting uvicorn"
exec uv run uvicorn automail.main:app --host 0.0.0.0 --port 8080 $RELOAD_FLAG
